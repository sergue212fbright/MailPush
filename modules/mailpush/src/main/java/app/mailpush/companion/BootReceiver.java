package app.mailpush.companion;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import org.json.JSONArray;
import org.json.JSONObject;
import org.unifiedpush.android.connector.UnifiedPush;

public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                if (UnifiedPush.getSavedDistributor(context) == null) return;
                Vault vault = new Vault(context);
                JSONArray profiles = vault.all();
                for (int i = 0; i < profiles.length(); i++) {
                    synchronized (Vault.LOCK) {
                        JSONObject profile = vault.get(profiles.getJSONObject(i).getString("instance"));
                        if (profile == null) continue;
                        // Registering a random instance carries no mail or account
                        // identity. Do not wait for the native account SDK here:
                        // broadcasts have short execution deadlines. Incoming
                        // alerts still require a fresh ready-account check, and
                        // the account observer revokes signed-out profiles.
                        UnifiedPush.register(context, profile.getString("instance"), "MailPush", profile.optString("vapid", "").isEmpty() ? null : profile.getString("vapid"));
                    }
                }
            } catch (Exception ignored) { }
            finally { pending.finish(); }
        }, "mailpush-reregister").start();
    }
}
