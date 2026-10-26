package app.mailpush.companion;

import com.google.crypto.tink.apps.fixed_webpush.WebPushHybridDecrypt;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.interfaces.ECPrivateKey;
import java.security.interfaces.ECPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Arrays;

public class SecurityTest {
    private JSONObject fixture, profile, event;
    private long now;

    @Before public void setup() throws Exception {
        try (var input = getClass().getResourceAsStream("/interop.json")) {
            fixture = new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
        profile = fixture.getJSONObject("profile"); event = fixture.getJSONObject("event"); now = fixture.getLong("now");
    }

    private JSONObject validate() throws Exception {
        return EventPolicy.validate(event.toString().getBytes(StandardCharsets.UTF_8), true, profile.getString("instance"), profile, now);
    }

    @Test public void validBoundEventAccepted() throws Exception { assertEquals("new_mail", validate().getString("type")); }
    @Test public void plaintextRejected() { assertThrows(Exception.class, () -> EventPolicy.validate(event.toString().getBytes(StandardCharsets.UTF_8), false, profile.getString("instance"), profile, now)); }
    @Test public void unpairedRejected() throws Exception { profile.put("paired",false); assertThrows(Exception.class,this::validate); }
    @Test public void wrongSourceRejected() throws Exception { event.put("source","00000000-0000-0000-0000-000000000000"); assertThrows(Exception.class,this::validate); }
    @Test public void wrongBindingRejected() throws Exception { event.put("binding","00000000-0000-0000-0000-000000000000"); assertThrows(Exception.class,this::validate); }
    @Test public void unknownMailboxRejected() throws Exception { event.put("mailbox","unapproved"); assertThrows(Exception.class,this::validate); }
    @Test public void calendarAndUnknownEventsRejected() throws Exception { event.put("type","calendar_reminder"); assertThrows(Exception.class,this::validate); }
    @Test public void expiredRejected() throws Exception { event.put("expires_at",now); assertThrows(Exception.class,this::validate); }
    @Test public void futureEventRejected() throws Exception { event.put("created_at",now+1000); assertThrows(Exception.class,this::validate); }
    @Test public void excessiveLifetimeRejected() throws Exception { event.put("expires_at",now+90000); assertThrows(Exception.class,this::validate); }
    @Test public void floatVersionRejected() throws Exception { event.put("v",2.5); assertThrows(Exception.class,this::validate); }
    @Test public void stringTimeRejected() throws Exception { event.put("created_at",Long.toString(now)); assertThrows(Exception.class,this::validate); }
    @Test public void oversizedPreviewRejected() throws Exception { event.put("subject","x".repeat(241)); assertThrows(Exception.class,this::validate); }
    @Test public void oversizedPacketRejected() { assertThrows(Exception.class, () -> EventPolicy.validate(new byte[4097],true,profile.getString("instance"),profile,now)); }
    @Test public void invalidUtf8Rejected() { assertThrows(Exception.class, () -> EventPolicy.validate(new byte[]{(byte)0xc3,0x28},true,profile.getString("instance"),profile,now)); }
    @Test public void controlBidiAndUnicodeLineCharactersStripped() { assertEquals("SafeSubject",EventPolicy.safeText("Safe\n\u202e\u2028\u2029Subject")); }

    private WebPushHybridDecrypt decryptor() throws Exception {
        KeyFactory factory = KeyFactory.getInstance("EC");
        ECPublicKey pub = (ECPublicKey) factory.generatePublic(new X509EncodedKeySpec(PairingCrypto.unb64(fixture.getString("public_x509"))));
        ECPrivateKey priv = (ECPrivateKey) factory.generatePrivate(new PKCS8EncodedKeySpec(PairingCrypto.unb64(fixture.getString("private_pkcs8"))));
        return new WebPushHybridDecrypt.Builder().withAuthSecret(PairingCrypto.unb64(fixture.getString("auth")))
            .withRecipientPublicKey(pub).withRecipientPrivateKey(priv).build();
    }

    @Test public void pythonCiphertextDecryptedByTink() throws Exception {
        byte[] clear = decryptor().decrypt(PairingCrypto.unb64(fixture.getString("ciphertext")),null);
        assertEquals(2048,clear.length);
        JSONObject checked = EventPolicy.validate(clear,true,profile.getString("instance"),profile,now);
        assertEquals("Synthetic private subject",checked.getString("subject"));
    }
    @Test public void tamperedCiphertextRejectedByTink() throws Exception {
        byte[] cipher = PairingCrypto.unb64(fixture.getString("ciphertext")); cipher[cipher.length-1] ^= 1;
        assertThrows(Exception.class, () -> decryptor().decrypt(cipher,null));
    }
    @Test public void canonicalFingerprintMatchesPython() throws Exception {
        assertEquals(profile.getString("pending_fingerprint"),PairingCrypto.fingerprint(fixture.getJSONObject("bundle")));
    }
    @Test public void pythonReceiptVerified() throws Exception {
        JSONObject receipt = PairingCrypto.verifyReceipt(profile,PairingCrypto.unb64(fixture.getString("receipt")),now);
        assertEquals(profile.getString("source"),receipt.getString("source"));
    }
    @Test public void receiptCannotChangeBinding() throws Exception {
        profile.put("instance","00000000-0000-0000-0000-000000000000");
        assertThrows(Exception.class, () -> PairingCrypto.verifyReceipt(profile,PairingCrypto.unb64(fixture.getString("receipt")),now));
    }
    @Test public void expiredPairingRejected() throws Exception {
        assertThrows(Exception.class, () -> PairingCrypto.verifyReceipt(profile,PairingCrypto.unb64(fixture.getString("receipt")),now+86401));
    }
    @Test public void wrongReceiptKeyRejected() throws Exception {
        profile.put("pending_key",PairingCrypto.b64(new byte[32]));
        assertThrows(Exception.class, () -> PairingCrypto.verifyReceipt(profile,PairingCrypto.unb64(fixture.getString("receipt")),now));
    }
    @Test public void generateJavaPairingRequestForPythonVerification() throws Exception {
        byte[] key = PairingCrypto.unb64(profile.getString("pending_key"));
        Path out = Path.of("build","interop"); Files.createDirectories(out);
        Files.write(out.resolve("java-request.mailpush"),PairingCrypto.export(fixture.getJSONObject("bundle"),key));
        Arrays.fill(key,(byte)0);
    }
}
