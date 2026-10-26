package app.mailpush.companion;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Profiles and subscription auth material stay wrapped by an Android Keystore key. */
final class Vault {
    private static final String ALIAS = "mailpush.profiles.v1";
    static final Object LOCK = new Object();
    interface Edit { void apply(JSONObject profile) throws Exception; }
    private final AtomicFile file;

    Vault(Context context) {
        file = new AtomicFile(new File(context.getNoBackupFilesDir(), "mailpush-profiles.gcm"));
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(ALIAS, null);
    }

    /** WorkManager persists input Data. Never give it a decrypted alert body. */
    byte[] sealWork(String instance, byte[] clear) throws Exception {
        synchronized (LOCK) {
            if (instance == null || instance.length() > 80 || clear.length > 4096) throw new SecurityException();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            cipher.updateAAD(("MailPush work v1\0" + instance).getBytes(StandardCharsets.UTF_8));
            byte[] body = cipher.doFinal(clear), encoded = new byte[12 + body.length];
            System.arraycopy(cipher.getIV(), 0, encoded, 0, 12);
            System.arraycopy(body, 0, encoded, 12, body.length);
            return encoded;
        }
    }

    byte[] openWork(String instance, byte[] encoded) throws Exception {
        synchronized (LOCK) {
            if (instance == null || instance.length() > 80 || encoded == null || encoded.length < 28 || encoded.length > 4124) throw new SecurityException();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Arrays.copyOfRange(encoded, 0, 12)));
            cipher.updateAAD(("MailPush work v1\0" + instance).getBytes(StandardCharsets.UTF_8));
            return cipher.doFinal(Arrays.copyOfRange(encoded, 12, encoded.length));
        }
    }

    JSONArray all() throws Exception {
        synchronized (LOCK) { return read(); }
    }

    private JSONArray read() throws Exception {
        File base = file.getBaseFile(), backup = new File(base.getPath() + ".bak");
        // AtomicFile restores a legacy backup in readFully(). Treating a missing
        // base as an empty vault first would silently lose recoverable profiles.
        if (!base.exists() && !backup.exists()) return new JSONArray();
        if (base.length() > 262144 || backup.length() > 262144) throw new SecurityException("Vault too large");
        byte[] encoded = file.readFully();
        if (encoded.length < 29 || encoded.length > 262144) throw new SecurityException("Vault damaged");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Arrays.copyOfRange(encoded, 0, 12)));
        cipher.updateAAD("MailPush vault v1".getBytes(StandardCharsets.UTF_8));
        byte[] clear = cipher.doFinal(Arrays.copyOfRange(encoded, 12, encoded.length));
        try { return new JSONArray(new String(clear, StandardCharsets.UTF_8)); }
        finally { Arrays.fill(clear, (byte) 0); }
    }

    JSONObject get(String instance) throws Exception {
        synchronized (LOCK) {
            JSONArray rows = read();
            for (int i = 0; i < rows.length(); i++) {
                JSONObject row = rows.getJSONObject(i);
                if (instance.equals(row.getString("instance"))) return row;
            }
            return null;
        }
    }

    void update(String instance, Edit edit) throws Exception {
        synchronized (LOCK) {
            JSONObject profile = get(instance);
            if (profile == null) return;
            edit.apply(profile);
            put(profile);
        }
    }

    void put(JSONObject profile) throws Exception {
        synchronized (LOCK) {
            JSONArray old = read(), next = new JSONArray();
            boolean found = false;
            for (int i = 0; i < old.length(); i++) {
                JSONObject row = old.getJSONObject(i);
                if (row.getString("instance").equals(profile.getString("instance"))) { next.put(profile); found = true; }
                else next.put(row);
            }
            if (!found) {
                if (next.length() >= 8) throw new IllegalStateException("Eight profiles maximum");
                next.put(profile);
            }
            write(next);
        }
    }

    void remove(String instance) throws Exception {
        synchronized (LOCK) {
            JSONArray old = read(), next = new JSONArray();
            for (int i = 0; i < old.length(); i++) if (!instance.equals(old.getJSONObject(i).getString("instance"))) next.put(old.getJSONObject(i));
            write(next);
        }
    }

    private void write(JSONArray rows) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        cipher.updateAAD("MailPush vault v1".getBytes(StandardCharsets.UTF_8));
        byte[] clear = rows.toString().getBytes(StandardCharsets.UTF_8);
        byte[] body;
        try { body = cipher.doFinal(clear); } finally { Arrays.fill(clear, (byte) 0); }
        FileOutputStream output = null;
        try {
            output = file.startWrite();
            output.write(cipher.getIV()); output.write(body);
            file.finishWrite(output);
        } catch (Exception error) {
            if (output != null) file.failWrite(output);
            throw error;
        }
    }
}
