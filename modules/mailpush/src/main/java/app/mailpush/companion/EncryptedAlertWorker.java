package app.mailpush.companion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.ForegroundInfo;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import java.util.Arrays;

/** Durable Android scheduling without persisting a decrypted notification. */
public final class EncryptedAlertWorker extends Worker {
    public EncryptedAlertWorker(@NonNull Context context, @NonNull WorkerParameters parameters) {
        super(context, parameters);
    }

    @NonNull @Override public Result doWork() {
        byte[] clear = null;
        try {
            if (isStopped()) return Result.success();
            // Restored jobs can start during Application.onCreate, just before
            // the Proton adapter installs. Preserve the encrypted job and retry
            // instead of treating that startup gap as a processed alert.
            if (!MailPushIntegration.initialized()) return Result.retry();
            String instance = getInputData().getString("instance");
            clear = new Vault(getApplicationContext()).openWork(instance, getInputData().getByteArray("sealed"));
            if (!isStopped()) MailPushService.deliver(getApplicationContext(), instance, clear);
            return Result.success(); // Processed; not an acknowledgement to the connector.
        } catch (Exception ignored) {
            return Result.failure(); // Lost keys/tampering must not retry or log plaintext.
        } finally { if (clear != null) Arrays.fill(clear, (byte) 0); }
    }

    /** WorkManager needs a foreground notification for expedited jobs before API 31. */
    @NonNull @Override public ForegroundInfo getForegroundInfo() {
        Context context = getApplicationContext();
        String channelId = "mailpush_processing";
        NotificationChannel channel = new NotificationChannel(channelId, "Encrypted push processing", NotificationManager.IMPORTANCE_LOW);
        channel.setShowBadge(false);
        context.getSystemService(NotificationManager.class).createNotificationChannel(channel);
        // API 29/30 can ask for foreground info before Application startup has
        // installed the host adapter. Keep that path independent of host state
        // so doWork can apply its normal startup retry instead of crashing.
        int icon = MailPushIntegration.initialized()
            ? MailPushIntegration.host().notificationIcon() : R.drawable.ic_notification;
        Notification notice = new Notification.Builder(context, channelId)
            .setSmallIcon(icon).setContentTitle("Proton Mail")
            .setContentText("Checking an encrypted alert").setOngoing(true).build();
        return new ForegroundInfo(776802, notice);
    }
}
