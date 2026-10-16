# Reproducible Android build environment for the Wana app (no Android Studio needed):
#   docker build -t wana-android mobile/build-env
#   docker run --rm -v "$PWD/mobile:/app" -w /app/android wana-android sh gradlew assembleDebug
FROM eclipse-temurin:21-jdk
ENV ANDROID_HOME=/opt/android-sdk
RUN apt-get update && apt-get install -y --no-install-recommends unzip curl && rm -rf /var/lib/apt/lists/* \
 && mkdir -p $ANDROID_HOME/cmdline-tools \
 && curl -sSL -o /tmp/tools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
 && unzip -q /tmp/tools.zip -d $ANDROID_HOME/cmdline-tools && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
 && rm /tmp/tools.zip \
 && yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses > /dev/null \
 && $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0" > /dev/null
