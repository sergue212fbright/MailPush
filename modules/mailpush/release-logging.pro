# Privacy release: remove Android/Timber log calls throughout the combined APK.
# Operational failures remain visible as sanitized status codes in setup.
-assumenosideeffects class android.util.Log {
    public static *** v(...);
    public static *** d(...);
    public static *** i(...);
    public static *** w(...);
    public static *** e(...);
    public static *** wtf(...);
}
-assumenosideeffects class timber.log.Timber {
    public static void v(...);
    public static void d(...);
    public static void i(...);
    public static void w(...);
    public static void e(...);
}
-assumenosideeffects class timber.log.Timber$Forest {
    public void v(...);
    public void d(...);
    public void i(...);
    public void w(...);
    public void e(...);
}
