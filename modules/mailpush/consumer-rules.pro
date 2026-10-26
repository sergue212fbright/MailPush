# The host creates this one integration entry point; manifest rules keep components.
-keep class app.mailpush.companion.MailPushIntegration { public *; }
-keep class app.mailpush.companion.EncryptedAlertWorker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}
