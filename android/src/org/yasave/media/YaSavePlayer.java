package org.yasave.media;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.MediaMetadata;
import android.media.MediaPlayer;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.Log;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Native audio player for YaSave (main app process).
 *
 * MediaPlayer + MediaSession (shade / lock screen controls) + MediaStyle notification,
 * kept alive by YaSaveMediaService (foreground, type mediaPlayback).
 * Python (core/player.py) calls the public methods through pyjnius from any thread;
 * work is posted to the main looper. next / prev / ended are queued for Python
 * (pollCommand), which owns the queue and resolves stream URLs.
 * Every step logs with tag "YaSave":  adb logcat -s YaSave
 */
public final class YaSavePlayer {
    private static final String TAG = "YaSave";
    private static final String CHANNEL_ID = "yasave_playback";
    private static final int NOTIFICATION_ID = 7301;
    private static final long PREV_RESTART_MS = 3000;

    private static final String ACTION_TOGGLE = "org.yasave.media.TOGGLE";
    private static final String ACTION_NEXT = "org.yasave.media.NEXT";
    private static final String ACTION_PREV = "org.yasave.media.PREV";
    private static final String ACTION_STOP = "org.yasave.media.STOP";

    private static YaSavePlayer sInstance;

    private final Context ctx;
    private final Handler main;
    private final NotificationManager notifications;
    private final AudioManager audio;
    private final ConcurrentLinkedQueue<String> commands = new ConcurrentLinkedQueue<>();

    private MediaPlayer player;
    private MediaSession session;
    private AudioFocusRequest focusRequest;
    private BroadcastReceiver receiver;
    private Service service;
    private boolean serviceRequested = false;
    private boolean foreground = false;

    // State shared with Python (read from other threads)
    private volatile String state = "idle";       // idle | buffering | playing | paused | ended | error
    private volatile String error = "";
    private volatile String notifError = "";
    private volatile String title = "";
    private volatile String artist = "";
    private volatile long durationMs = 0;
    private volatile long positionMs = 0;
    private volatile long positionAt = 0;
    private volatile boolean hasPrev = false;
    private volatile boolean hasNext = false;
    private volatile int seq = 0;
    private volatile Bitmap cover;
    private volatile boolean resumeOnFocusGain = false;
    private volatile boolean testMode = false;

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            if (player != null && "playing".equals(state)) {
                try {
                    positionMs = player.getCurrentPosition();
                    positionAt = System.currentTimeMillis();
                } catch (Exception ignored) {
                }
                main.postDelayed(this, 1000);
            }
        }
    };

    // ------------------------------------------------------------------
    // Singleton / service glue
    // ------------------------------------------------------------------

    public static synchronized YaSavePlayer get(Context any) {
        if (sInstance == null) {
            Log.i(TAG, "player: create (sdk " + Build.VERSION.SDK_INT + ", " + Build.MANUFACTURER + ")");
            sInstance = new YaSavePlayer(any.getApplicationContext());
        }
        return sInstance;
    }

    static synchronized void attachService(Service s) {
        YaSavePlayer p = sInstance;
        if (p == null) {
            // Should not happen; still satisfy the startForeground() contract.
            Log.w(TAG, "service started without player, stopping");
            p = get(s);
        }
        p.onServiceAttached(s);
    }

    static synchronized void detachService(Service s) {
        if (sInstance != null && sInstance.service == s) {
            sInstance.service = null;
            sInstance.foreground = false;
            sInstance.serviceRequested = false;
        }
    }

    static void onTaskRemoved() {
        final YaSavePlayer p = sInstance;
        if (p != null && !"playing".equals(p.state) && !"buffering".equals(p.state)) {
            p.main.post(new Runnable() {
                @Override
                public void run() {
                    p.doStop();
                }
            });
        }
    }

    private YaSavePlayer(Context appCtx) {
        this.ctx = appCtx;
        this.main = new Handler(Looper.getMainLooper());
        this.notifications = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        this.audio = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
        main.post(new Runnable() {
            @Override
            public void run() {
                setup();
            }
        });
    }

    // ------------------------------------------------------------------
    // Public API (any thread)
    // ------------------------------------------------------------------

    public void play(final String url, final String newTitle, final String newArtist,
                     final String coverRef, final long durationHintMs,
                     final boolean prev, final boolean next) {
        Log.i(TAG, "play: '" + newTitle + "' prev=" + prev + " next=" + next);
        testMode = false;
        seq++;
        title = newTitle != null ? newTitle : "";
        artist = newArtist != null ? newArtist : "";
        durationMs = Math.max(0, durationHintMs);
        positionMs = 0;
        positionAt = System.currentTimeMillis();
        hasPrev = prev;
        hasNext = next;
        error = "";
        state = "buffering";
        cover = null;
        final int mySeq = seq;
        loadCoverAsync(coverRef, mySeq);
        main.post(new Runnable() {
            @Override
            public void run() {
                ensureService();
                startPlayback(url, mySeq);
            }
        });
    }

    public void setNavigation(boolean prev, boolean next) {
        hasPrev = prev;
        hasNext = next;
        post(new Runnable() {
            @Override
            public void run() {
                publish();
            }
        });
    }

    public void pause() {
        post(new Runnable() {
            @Override
            public void run() {
                doPause();
            }
        });
    }

    public void resume() {
        post(new Runnable() {
            @Override
            public void run() {
                doResume();
            }
        });
    }

    public void toggle() {
        post(new Runnable() {
            @Override
            public void run() {
                doToggle();
            }
        });
    }

    public void seekTo(final long ms) {
        post(new Runnable() {
            @Override
            public void run() {
                doSeek(ms);
            }
        });
    }

    /** Same rule as the in-app button: restart if played > 3 s or first track, else previous. */
    public void previous() {
        post(new Runnable() {
            @Override
            public void run() {
                onPrevPressed();
            }
        });
    }

    public void stop() {
        post(new Runnable() {
            @Override
            public void run() {
                doStop();
            }
        });
    }

    /**
     * Settings -> "Проверить плеер в шторке": shows a test notification through the
     * same path as real playback (channel, MediaSession, foreground service), no audio.
     * Does nothing while real music is loaded.
     */
    public void startSelfTest() {
        post(new Runnable() {
            @Override
            public void run() {
                if (player != null && !"idle".equals(state)) {
                    Log.i(TAG, "self-test: skipped, music is loaded");
                    return;
                }
                Log.i(TAG, "self-test: start");
                testMode = true;
                seq++;
                title = "YaSave: проверка плеера";
                artist = "Если вы видите это уведомление, плеер в шторке работает";
                durationMs = 0;
                positionMs = 0;
                state = "paused";
                error = "";
                ensureService();
                publish();
            }
        });
    }

    /** Ends the self-test notification (no effect on real playback). */
    public void endSelfTest() {
        post(new Runnable() {
            @Override
            public void run() {
                if (testMode && player == null) {
                    Log.i(TAG, "self-test: end");
                    testMode = false;
                    doStop();
                }
            }
        });
    }

    private boolean sessionActive() {
        try {
            return session != null && session.isActive();
        } catch (Exception e) {
            return false;
        }
    }

    private boolean channelExists() {
        try {
            return Build.VERSION.SDK_INT < 26 || notifications.getNotificationChannel(CHANNEL_ID) != null;
        } catch (Exception e) {
            return false;
        }
    }

    /** Returns "next", "prev", "ended", "stop" or null. */
    public String pollCommand() {
        return commands.poll();
    }

    public String getStateJson() {
        long pos = currentPosition();
        return "{\"state\":\"" + state + "\""
                + ",\"position_ms\":" + pos
                + ",\"duration_ms\":" + durationMs
                + ",\"seq\":" + seq
                + ",\"has_prev\":" + hasPrev
                + ",\"has_next\":" + hasNext
                + ",\"foreground\":" + foreground
                + ",\"service\":" + (service != null)
                + ",\"session\":" + (session != null)
                + ",\"session_active\":" + sessionActive()
                + ",\"channel\":" + channelExists()
                + ",\"test\":" + testMode
                + ",\"error\":\"" + escape(error) + "\""
                + ",\"notification_error\":\"" + escape(notifError) + "\""
                + ",\"title\":\"" + escape(title) + "\"}";
    }

    // ------------------------------------------------------------------
    // System status / settings shortcuts (for the "background playback" screen)
    // ------------------------------------------------------------------

    public static String systemStatus(Context any) {
        Context c = any.getApplicationContext();
        boolean notif = true;
        boolean battery = false;
        boolean channelOk = true;
        try {
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (Build.VERSION.SDK_INT >= 24) {
                notif = nm.areNotificationsEnabled();
            }
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel ch = nm.getNotificationChannel(CHANNEL_ID);
                channelOk = ch == null || ch.getImportance() != NotificationManager.IMPORTANCE_NONE;
            }
        } catch (Exception e) {
            Log.w(TAG, "status: notifications", e);
        }
        try {
            if (Build.VERSION.SDK_INT >= 23) {
                PowerManager pm = (PowerManager) c.getSystemService(Context.POWER_SERVICE);
                battery = pm.isIgnoringBatteryOptimizations(c.getPackageName());
            } else {
                battery = true;
            }
        } catch (Exception e) {
            Log.w(TAG, "status: battery", e);
        }
        return "{\"notifications_enabled\":" + notif
                + ",\"channel_enabled\":" + channelOk
                + ",\"battery_unrestricted\":" + battery
                + ",\"sdk\":" + Build.VERSION.SDK_INT
                + ",\"manufacturer\":\"" + escape(Build.MANUFACTURER) + "\""
                + ",\"model\":\"" + escape(Build.MODEL) + "\"}";
    }

    /** which: notifications | battery | app | autostart. Returns false if nothing could be opened. */
    public static boolean openSettings(Activity activity, String which) {
        String pkg = activity.getPackageName();
        Intent[] candidates;
        if ("notifications".equals(which) && Build.VERSION.SDK_INT >= 26) {
            candidates = new Intent[]{
                new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, pkg),
                appDetails(pkg)};
        } else if ("battery".equals(which) && Build.VERSION.SDK_INT >= 23) {
            candidates = new Intent[]{
                new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).setData(Uri.parse("package:" + pkg)),
                new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
                appDetails(pkg)};
        } else if ("autostart".equals(which)) {
            // vivo / iQOO (Origin OS, Funtouch): background / autostart manager
            candidates = new Intent[]{
                new Intent().setClassName("com.vivo.permissionmanager",
                        "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
                new Intent().setClassName("com.iqoo.secure",
                        "com.iqoo.secure.ui.phoneoptimize.BgStartUpManager"),
                new Intent().setClassName("com.iqoo.secure",
                        "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"),
                appDetails(pkg)};
        } else {
            candidates = new Intent[]{appDetails(pkg)};
        }
        for (Intent i : candidates) {
            try {
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                activity.startActivity(i);
                Log.i(TAG, "openSettings(" + which + "): " + i);
                return true;
            } catch (Exception e) {
                Log.w(TAG, "openSettings(" + which + ") failed: " + i + " " + e);
            }
        }
        return false;
    }

    private static Intent appDetails(String pkg) {
        return new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).setData(Uri.parse("package:" + pkg));
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    private void post(Runnable r) {
        main.post(r);
    }

    private void setup() {
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                // LOW: no sound / heads-up, but visible in the shade and on the lock screen
                NotificationChannel channel = new NotificationChannel(
                        CHANNEL_ID, "Воспроизведение", NotificationManager.IMPORTANCE_LOW);
                channel.setDescription("Плеер YaSave в шторке и на экране блокировки");
                channel.setShowBadge(false);
                channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
                notifications.createNotificationChannel(channel);
                Log.i(TAG, "setup: notification channel ready");
            }
        } catch (Exception e) {
            Log.e(TAG, "setup: channel failed", e);
        }

        try {
            session = new MediaSession(ctx, "YaSave");
            session.setCallback(new MediaSession.Callback() {
                @Override
                public void onPlay() {
                    Log.i(TAG, "session: play");
                    doResume();
                }

                @Override
                public void onPause() {
                    Log.i(TAG, "session: pause");
                    doPause();
                }

                @Override
                public void onSkipToNext() {
                    Log.i(TAG, "session: next");
                    commands.add("next");
                }

                @Override
                public void onSkipToPrevious() {
                    Log.i(TAG, "session: prev");
                    onPrevPressed();
                }

                @Override
                public void onSeekTo(long pos) {
                    doSeek(pos);
                }

                @Override
                public void onStop() {
                    Log.i(TAG, "session: stop");
                    doStop();
                }
            }, main);
            if (Build.VERSION.SDK_INT < 27) {
                session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS
                        | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
            }
            Log.i(TAG, "setup: media session ready");
        } catch (Exception e) {
            Log.e(TAG, "setup: media session failed", e);
            session = null;
        }

        try {
            receiver = new BroadcastReceiver() {
                @Override
                public void onReceive(Context context, Intent intent) {
                    String action = intent != null ? intent.getAction() : null;
                    Log.i(TAG, "notification action: " + action);
                    if (ACTION_TOGGLE.equals(action)) {
                        doToggle();
                    } else if (ACTION_NEXT.equals(action)) {
                        commands.add("next");
                    } else if (ACTION_PREV.equals(action)) {
                        onPrevPressed();
                    } else if (ACTION_STOP.equals(action)) {
                        doStop();
                    } else if (AudioManager.ACTION_AUDIO_BECOMING_NOISY.equals(action)) {
                        doPause();
                    }
                }
            };
            IntentFilter filter = new IntentFilter();
            filter.addAction(ACTION_TOGGLE);
            filter.addAction(ACTION_NEXT);
            filter.addAction(ACTION_PREV);
            filter.addAction(ACTION_STOP);
            filter.addAction(AudioManager.ACTION_AUDIO_BECOMING_NOISY);
            if (Build.VERSION.SDK_INT >= 33) {
                ctx.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
            } else {
                ctx.registerReceiver(receiver, filter);
            }
            Log.i(TAG, "setup: action receiver ready");
        } catch (Exception e) {
            Log.e(TAG, "setup: receiver failed", e);
        }
    }

    private void ensureService() {
        if (service != null || serviceRequested) {
            return;
        }
        try {
            Intent i = new Intent(ctx, YaSaveMediaService.class);
            if (Build.VERSION.SDK_INT >= 26) {
                ctx.startForegroundService(i);
            } else {
                ctx.startService(i);
            }
            serviceRequested = true;
            Log.i(TAG, "service: start requested");
        } catch (Exception e) {
            notifError = "Сервис не запустился: " + e.getClass().getSimpleName() + ": " + e.getMessage();
            Log.e(TAG, "service: start failed", e);
        }
    }

    private void onServiceAttached(Service s) {
        service = s;
        serviceRequested = false;
        foreground = false;
        Log.i(TAG, "service: attached, going foreground");
        if ("idle".equals(state)) {
            // Started but nothing to show (e.g. stopped meanwhile): leave cleanly
            Notification n = buildNotification();
            startForegroundSafe(n);
            leaveForeground(true);
            s.stopSelf();
            return;
        }
        updateNotification();
    }

    // ------------------------------------------------------------------
    // Playback (main thread)
    // ------------------------------------------------------------------

    private void startPlayback(String url, final int mySeq) {
        releasePlayer();
        try {
            final MediaPlayer mp = new MediaPlayer();
            player = mp;
            mp.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build());
            try {
                mp.setWakeMode(ctx, PowerManager.PARTIAL_WAKE_LOCK);
            } catch (Exception e) {
                Log.w(TAG, "wake lock unavailable", e);
            }
            mp.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                @Override
                public void onPrepared(MediaPlayer p) {
                    if (p != player || mySeq != seq) {
                        return;
                    }
                    int d = p.getDuration();
                    if (d > 0) {
                        durationMs = d;
                    }
                    if (requestFocus()) {
                        p.start();
                        state = "playing";
                    } else {
                        state = "paused";
                    }
                    Log.i(TAG, "prepared: " + state + ", duration " + durationMs);
                    positionMs = 0;
                    positionAt = System.currentTimeMillis();
                    publish();
                    main.removeCallbacks(ticker);
                    main.post(ticker);
                }
            });
            mp.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                @Override
                public void onCompletion(MediaPlayer p) {
                    if (p != player) {
                        return;
                    }
                    Log.i(TAG, "completed, asking app for the next track");
                    state = "ended";
                    positionMs = durationMs;
                    positionAt = System.currentTimeMillis();
                    publish();
                    commands.add("ended");
                }
            });
            mp.setOnErrorListener(new MediaPlayer.OnErrorListener() {
                @Override
                public boolean onError(MediaPlayer p, int what, int extra) {
                    if (p != player) {
                        return true;
                    }
                    Log.e(TAG, "MediaPlayer error " + what + "/" + extra);
                    state = "error";
                    error = "Ошибка воспроизведения (" + what + "/" + extra + ")";
                    publish();
                    return true;
                }
            });
            mp.setOnInfoListener(new MediaPlayer.OnInfoListener() {
                @Override
                public boolean onInfo(MediaPlayer p, int what, int extra) {
                    if (p != player) {
                        return false;
                    }
                    if (what == MediaPlayer.MEDIA_INFO_BUFFERING_START && "playing".equals(state)) {
                        state = "buffering";
                        publish();
                    } else if (what == MediaPlayer.MEDIA_INFO_BUFFERING_END && "buffering".equals(state)) {
                        state = p.isPlaying() ? "playing" : "paused";
                        positionAt = System.currentTimeMillis();
                        publish();
                    }
                    return false;
                }
            });
            mp.setDataSource(url);
            state = "buffering";
            publish();
            mp.prepareAsync();
        } catch (Exception e) {
            Log.e(TAG, "startPlayback failed", e);
            state = "error";
            error = "Не удалось открыть поток: " + e.getClass().getSimpleName();
            publish();
        }
    }

    private long currentPosition() {
        long pos = positionMs;
        if ("playing".equals(state) && positionAt > 0) {
            pos += System.currentTimeMillis() - positionAt;
        }
        if (durationMs > 0 && pos > durationMs) {
            pos = durationMs;
        }
        return pos;
    }

    private void doToggle() {
        if ("playing".equals(state) || "buffering".equals(state)) {
            doPause();
        } else {
            doResume();
        }
    }

    private void doPause() {
        if (player == null) {
            return;
        }
        try {
            if (player.isPlaying()) {
                player.pause();
            }
            positionMs = player.getCurrentPosition();
            positionAt = System.currentTimeMillis();
        } catch (Exception e) {
            Log.w(TAG, "pause", e);
        }
        if (!"error".equals(state)) {
            state = "paused";
        }
        main.removeCallbacks(ticker);
        publish();
    }

    private void doResume() {
        if (player == null) {
            return;
        }
        if ("ended".equals(state)) {
            doSeek(0);
            state = "paused";
        }
        if (!"paused".equals(state)) {
            return;
        }
        if (!requestFocus()) {
            return;
        }
        try {
            player.start();
            state = "playing";
            positionAt = System.currentTimeMillis();
        } catch (Exception e) {
            Log.w(TAG, "resume", e);
        }
        publish();
        main.removeCallbacks(ticker);
        main.post(ticker);
    }

    private void doSeek(long ms) {
        if (player == null) {
            return;
        }
        try {
            player.seekTo((int) Math.max(0, ms));
            positionMs = Math.max(0, ms);
            positionAt = System.currentTimeMillis();
        } catch (Exception e) {
            Log.w(TAG, "seek", e);
        }
        publish();
    }

    private void onPrevPressed() {
        if (currentPosition() > PREV_RESTART_MS || !hasPrev) {
            doSeek(0);
            if ("ended".equals(state)) {
                doResume();
            }
        } else {
            commands.add("prev");
        }
    }

    private void doStop() {
        Log.i(TAG, "stop");
        releasePlayer();
        state = "idle";
        positionMs = 0;
        abandonFocus();
        try {
            if (session != null) {
                session.setActive(false);
            }
        } catch (Exception ignored) {
        }
        leaveForeground(true);
        Service s = service;
        if (s != null) {
            s.stopSelf();
        }
        commands.add("stop");
    }

    private void releasePlayer() {
        main.removeCallbacks(ticker);
        if (player != null) {
            try {
                player.reset();
                player.release();
            } catch (Exception ignored) {
            }
            player = null;
        }
    }

    // ------------------------------------------------------------------
    // Audio focus
    // ------------------------------------------------------------------

    private final AudioManager.OnAudioFocusChangeListener focusListener =
            new AudioManager.OnAudioFocusChangeListener() {
                @Override
                public void onAudioFocusChange(int change) {
                    if (change == AudioManager.AUDIOFOCUS_LOSS) {
                        resumeOnFocusGain = false;
                        doPause();
                    } else if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT
                            || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) {
                        resumeOnFocusGain = "playing".equals(state);
                        doPause();
                    } else if (change == AudioManager.AUDIOFOCUS_GAIN && resumeOnFocusGain) {
                        resumeOnFocusGain = false;
                        doResume();
                    }
                }
            };

    private boolean requestFocus() {
        try {
            int result;
            if (Build.VERSION.SDK_INT >= 26) {
                if (focusRequest == null) {
                    focusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                            .setAudioAttributes(new AudioAttributes.Builder()
                                    .setUsage(AudioAttributes.USAGE_MEDIA)
                                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                                    .build())
                            .setOnAudioFocusChangeListener(focusListener, main)
                            .build();
                }
                result = audio.requestAudioFocus(focusRequest);
            } else {
                result = audio.requestAudioFocus(focusListener,
                        AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN);
            }
            return result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
        } catch (Exception e) {
            Log.w(TAG, "focus", e);
            return true;
        }
    }

    private void abandonFocus() {
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                if (focusRequest != null) {
                    audio.abandonAudioFocusRequest(focusRequest);
                }
            } else {
                audio.abandonAudioFocus(focusListener);
            }
        } catch (Exception ignored) {
        }
    }

    // ------------------------------------------------------------------
    // MediaSession + notification
    // ------------------------------------------------------------------

    private void publish() {
        updateSession();
        updateNotification();
    }

    private void updateSession() {
        if (session == null) {
            return;
        }
        try {
            MediaMetadata.Builder meta = new MediaMetadata.Builder()
                    .putString(MediaMetadata.METADATA_KEY_TITLE, title)
                    .putString(MediaMetadata.METADATA_KEY_ARTIST, artist)
                    .putLong(MediaMetadata.METADATA_KEY_DURATION, durationMs);
            Bitmap art = cover;
            if (art != null) {
                meta.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, art);
            }
            session.setMetadata(meta.build());

            // Prev is always available: it restarts the track when there is no previous one
            long actions = PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE
                    | PlaybackState.ACTION_PLAY_PAUSE | PlaybackState.ACTION_SEEK_TO
                    | PlaybackState.ACTION_STOP | PlaybackState.ACTION_SKIP_TO_PREVIOUS;
            if (hasNext) {
                actions |= PlaybackState.ACTION_SKIP_TO_NEXT;
            }
            int pbState;
            float speed = 0f;
            if ("playing".equals(state)) {
                pbState = PlaybackState.STATE_PLAYING;
                speed = 1f;
            } else if ("buffering".equals(state)) {
                pbState = PlaybackState.STATE_BUFFERING;
            } else if ("error".equals(state)) {
                pbState = PlaybackState.STATE_ERROR;
            } else if ("idle".equals(state)) {
                pbState = PlaybackState.STATE_STOPPED;
            } else {
                pbState = PlaybackState.STATE_PAUSED;
            }
            PlaybackState.Builder pb = new PlaybackState.Builder()
                    .setActions(actions)
                    .setState(pbState, currentPosition(), speed);
            if ("error".equals(state)) {
                pb.setErrorMessage(error);
            }
            session.setPlaybackState(pb.build());
            session.setActive(!"idle".equals(state));
        } catch (Exception e) {
            Log.e(TAG, "updateSession failed", e);
        }
    }

    private PendingIntent action(String name, int requestCode) {
        Intent intent = new Intent(name);
        intent.setPackage(ctx.getPackageName());
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        return PendingIntent.getBroadcast(ctx, requestCode, intent, flags);
    }

    private PendingIntent openApp() {
        try {
            Intent launch = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName());
            if (launch == null) {
                return null;
            }
            launch.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= 23) {
                flags |= PendingIntent.FLAG_IMMUTABLE;
            }
            return PendingIntent.getActivity(ctx, 10, launch, flags);
        } catch (Exception e) {
            return null;
        }
    }

    @SuppressWarnings("deprecation")
    private Notification buildNotification() {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(ctx, CHANNEL_ID)
                : new Notification.Builder(ctx);
        boolean playing = "playing".equals(state) || "buffering".equals(state);
        b.setSmallIcon(ctx.getApplicationInfo().icon)
                .setContentTitle(title.length() > 0 ? title : "YaSave")
                .setContentText(artist)
                .setOngoing(playing)
                .setShowWhen(false)
                .setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setCategory(Notification.CATEGORY_TRANSPORT)
                .setDeleteIntent(action(ACTION_STOP, 4));
        if (Build.VERSION.SDK_INT < 26) {
            b.setPriority(Notification.PRIORITY_LOW);
        }
        if (Build.VERSION.SDK_INT >= 31) {
            b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        }
        PendingIntent content = openApp();
        if (content != null) {
            b.setContentIntent(content);
        }
        Bitmap art = cover;
        if (art != null) {
            b.setLargeIcon(art);
        }
        b.addAction(new Notification.Action(android.R.drawable.ic_media_previous, "Назад", action(ACTION_PREV, 1)));
        b.addAction(new Notification.Action(
                playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
                playing ? "Пауза" : "Играть", action(ACTION_TOGGLE, 2)));
        b.addAction(new Notification.Action(android.R.drawable.ic_media_next, "Далее", action(ACTION_NEXT, 3)));
        b.addAction(new Notification.Action(android.R.drawable.ic_menu_close_clear_cancel, "Закрыть", action(ACTION_STOP, 5)));
        Notification.MediaStyle style = new Notification.MediaStyle().setShowActionsInCompactView(0, 1, 2);
        if (session != null) {
            style.setMediaSession(session.getSessionToken());
        }
        b.setStyle(style);
        return b.build();
    }

    private void startForegroundSafe(Notification n) {
        Service s = service;
        if (s == null) {
            return;
        }
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                s.startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
            } else {
                s.startForeground(NOTIFICATION_ID, n);
            }
            foreground = true;
            notifError = "";
            Log.i(TAG, "notification: foreground started");
        } catch (Exception e) {
            // e.g. ForegroundServiceStartNotAllowedException / SecurityException (missing permission)
            notifError = "startForeground: " + e.getClass().getSimpleName() + ": " + e.getMessage();
            Log.e(TAG, "notification: startForeground failed", e);
        }
    }

    private void updateNotification() {
        if ("idle".equals(state)) {
            return;
        }
        try {
            Notification n = buildNotification();
            if (service != null && !foreground) {
                startForegroundSafe(n);
            } else if (service != null) {
                notifications.notify(NOTIFICATION_ID, n);
            } else {
                ensureService();
            }
        } catch (Exception e) {
            notifError = "notification: " + e.getClass().getSimpleName() + ": " + e.getMessage();
            Log.e(TAG, "notification: update failed", e);
        }
    }

    private void leaveForeground(boolean removeNotification) {
        Service s = service;
        try {
            if (s != null) {
                if (Build.VERSION.SDK_INT >= 24) {
                    s.stopForeground(removeNotification
                            ? Service.STOP_FOREGROUND_REMOVE : Service.STOP_FOREGROUND_DETACH);
                } else {
                    s.stopForeground(removeNotification);
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "stopForeground", e);
        }
        foreground = false;
        if (removeNotification) {
            try {
                notifications.cancel(NOTIFICATION_ID);
            } catch (Exception ignored) {
            }
        }
    }

    // ------------------------------------------------------------------
    // Cover loading (background thread)
    // ------------------------------------------------------------------

    private void loadCoverAsync(final String ref, final int mySeq) {
        if (ref == null || ref.length() == 0) {
            return;
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                Bitmap bmp = null;
                try {
                    if (ref.startsWith("http://") || ref.startsWith("https://")) {
                        HttpURLConnection conn = (HttpURLConnection) new URL(ref).openConnection();
                        conn.setConnectTimeout(8000);
                        conn.setReadTimeout(8000);
                        InputStream in = conn.getInputStream();
                        try {
                            bmp = BitmapFactory.decodeStream(in);
                        } finally {
                            in.close();
                            conn.disconnect();
                        }
                    } else {
                        bmp = BitmapFactory.decodeFile(ref);
                    }
                    if (bmp != null && (bmp.getWidth() > 512 || bmp.getHeight() > 512)) {
                        bmp = Bitmap.createScaledBitmap(bmp, 512, 512, true);
                    }
                } catch (Exception e) {
                    Log.w(TAG, "cover " + e);
                }
                final Bitmap result = bmp;
                main.post(new Runnable() {
                    @Override
                    public void run() {
                        if (mySeq == seq && result != null) {
                            cover = result;
                            publish();
                        }
                    }
                });
            }
        }).start();
    }

    private static String escape(String s) {
        if (s == null) {
            return "";
        }
        StringBuilder out = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':
                    out.append("\\\"");
                    break;
                case '\\':
                    out.append("\\\\");
                    break;
                case '\n':
                    out.append("\\n");
                    break;
                case '\r':
                    out.append("\\r");
                    break;
                case '\t':
                    out.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        return out.toString();
    }
}
