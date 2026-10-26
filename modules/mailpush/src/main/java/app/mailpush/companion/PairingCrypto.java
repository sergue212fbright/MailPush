package app.mailpush.companion;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

final class PairingCrypto {
    static byte[] random(int size) { byte[] bytes = new byte[size]; new SecureRandom().nextBytes(bytes); return bytes; }
    static String b64(byte[] bytes) { return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes); }
    static byte[] unb64(String value) { return Base64.getUrlDecoder().decode(value); }

    static byte[] export(JSONObject bundle, byte[] key) throws Exception {
        byte[] nonce = random(12);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, nonce));
        cipher.updateAAD("MailPush pairing v1".getBytes(StandardCharsets.UTF_8));
        return new JSONObject().put("format", "mailpush-pairing-v1").put("nonce", b64(nonce))
            .put("ciphertext", b64(cipher.doFinal(bundle.toString().getBytes(StandardCharsets.UTF_8))))
            .toString().getBytes(StandardCharsets.UTF_8);
    }

    static JSONObject receipt(byte[] body, byte[] key) throws Exception {
        if (body.length > 65536 || key.length != 32) throw new SecurityException("Invalid receipt");
        JSONObject envelope = new JSONObject(new String(body, StandardCharsets.UTF_8));
        if (envelope.length() != 3 || !"mailpush-receipt-v1".equals(envelope.getString("format"))) throw new SecurityException("Invalid receipt");
        byte[] nonce = unb64(envelope.getString("nonce"));
        if (nonce.length != 12) throw new SecurityException("Invalid nonce");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, nonce));
        cipher.updateAAD("MailPush receipt v1".getBytes(StandardCharsets.UTF_8));
        return new JSONObject(new String(cipher.doFinal(unb64(envelope.getString("ciphertext"))), StandardCharsets.UTF_8));
    }

    static JSONObject verifyReceipt(JSONObject profile, byte[] bytes, long now) throws Exception {
        long age = now - profile.getLong("pending_at");
        if (age < -300 || age > 86400) throw new SecurityException("Expired request");
        byte[] key = unb64(profile.getString("pending_key"));
        JSONObject receipt;
        try { receipt = receipt(bytes, key); } finally { Arrays.fill(key, (byte) 0); }
        long receiptAge = now - receipt.getLong("created_at");
        if (!receipt.getString("format").equals("mailpush-receipt-v2") || !receipt.getString("binding").equals(profile.getString("instance"))
                || !receipt.getString("fingerprint").equals(profile.getString("pending_fingerprint"))
                || !receipt.getJSONArray("mailboxes").toString().equals(profile.getJSONArray("mailboxes").toString())
                || receiptAge < -300 || receiptAge > 86400) throw new SecurityException("Receipt mismatch");
        EventPolicy.uuid(receipt.getString("source"));
        return receipt;
    }

    static String fingerprint(JSONObject bundle) throws Exception {
        StringBuilder value = new StringBuilder("MailPush binding v2\n");
        value.append(bundle.getString("binding")).append('\n').append(bundle.getString("endpoint")).append('\n')
            .append(bundle.getJSONObject("keys").getString("p256dh")).append('\n').append(bundle.getJSONObject("keys").getString("auth"));
        JSONArray mailboxes = bundle.getJSONArray("mailboxes");
        for (int i = 0; i < mailboxes.length(); i++) value.append('\n').append(mailboxes.getString(i));
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.toString().getBytes(StandardCharsets.UTF_8));
        StringBuilder hex = new StringBuilder();
        for (int i = 0; i < 12; i++) hex.append(String.format(java.util.Locale.ROOT, "%02x", digest[i] & 255));
        return hex.toString();
    }
}
