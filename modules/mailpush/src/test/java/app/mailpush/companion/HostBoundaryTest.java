package app.mailpush.companion;

import android.app.Activity;
import android.content.Context;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

/** A valid encrypted packet alone must never bypass the signed-in account boundary. */
public class HostBoundaryTest {
    private static MailPushIntegration.Host host(boolean ready, boolean failure) {
        return new MailPushIntegration.Host() {
            public List<MailPushIntegration.Account> accounts() { return List.of(); }
            public int notificationIcon() { return 0; }
            public boolean isAccountReady(String id) {
                if (failure) throw new IllegalStateException();
                return ready && id.equals("approved-account");
            }
            public void authorizeSettings(Activity a, Runnable allowed) { allowed.run(); }
            public void openInbox(Context c, String id) { }
        };
    }
    @Test public void readyAccountAccepted() throws Exception {
        MailPushIntegration.install(host(true,false));
        assertTrue(MailPushIntegration.ready(new JSONObject().put("account","approved-account")));
    }
    @Test public void differentAccountRejected() throws Exception {
        MailPushIntegration.install(host(true,false));
        assertFalse(MailPushIntegration.ready(new JSONObject().put("account","other")));
    }
    @Test public void signedOutAccountRejected() throws Exception {
        MailPushIntegration.install(host(false,false));
        assertFalse(MailPushIntegration.ready(new JSONObject().put("account","approved-account")));
    }
    @Test public void hostFailureIsClosed() throws Exception {
        MailPushIntegration.install(host(true,true));
        assertFalse(MailPushIntegration.ready(new JSONObject().put("account","approved-account")));
    }
    @Test public void missingAccountBindingRejected() {
        MailPushIntegration.install(host(true,false));
        assertFalse(MailPushIntegration.ready(new JSONObject()));
        assertFalse(MailPushIntegration.ready(null));
    }
}
