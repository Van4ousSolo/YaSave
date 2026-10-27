package org.yasave.media;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.util.Log;

/**
 * Foreground service (type mediaPlayback) that keeps the app process alive while
 * music plays and owns the player notification. It runs in the main app process
 * (no separate Python interpreter); all playback logic lives in YaSavePlayer.
 *
 * Declared in android/aar/AndroidManifest.xml, merged into the app manifest by Gradle.
 */
public class YaSaveMediaService extends Service {
    private static final String TAG = "YaSave";

    @Override
    public void onCreate() {
        super.onCreate();
        Log.i(TAG, "media service: onCreate");
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Log.i(TAG, "media service: onStartCommand");
        // startForeground() must happen right away (5 s limit after startForegroundService)
        YaSavePlayer.attachService(this);
        return START_NOT_STICKY;
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        Log.i(TAG, "media service: task removed");
        YaSavePlayer.onTaskRemoved();
        super.onTaskRemoved(rootIntent);
    }

    @Override
    public void onDestroy() {
        Log.i(TAG, "media service: onDestroy");
        YaSavePlayer.detachService(this);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
