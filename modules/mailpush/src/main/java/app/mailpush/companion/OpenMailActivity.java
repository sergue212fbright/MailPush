package app.mailpush.companion;

import android.app.Activity;
import android.os.Bundle;
import org.json.JSONObject;

/** Only local, immutable notification intents enter here; payloads supply no URL. */
public final class OpenMailActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            String instance = getIntent().getStringExtra("instance");
            JSONObject profile = instance == null ? null : new Vault(this).get(instance);
            if (profile != null && profile.optBoolean("paired")) {
                MailPushIntegration.cancelAlerts(this, instance);
                // The host checks fresh account state asynchronously before any
                // navigation. Never block Android's activity thread on the SDK.
                MailPushIntegration.host().openInbox(getApplicationContext(), profile.getString("account"));
            }
        } catch (Exception ignored) { /* No fallthrough to a different account. */ }
        finish();
    }
}
