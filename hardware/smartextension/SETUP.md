# Smart Extension Hardware Setup Guide

This guide will walk you through setting up the Arduino IDE, installing necessary dependencies, and flashing the ESP32 board with the Smart Extension firmware.

## Prerequisites
- An ESP32 development board.
- A micro-USB or USB-C cable (ensure it supports data transfer, not just charging).
- A computer running Windows, macOS, or Linux.

## 1. Install Arduino IDE
1. Download and install the latest [Arduino IDE](https://www.arduino.cc/en/software).
2. Open the Arduino IDE.

## 2. Add ESP32 Board Support
1. Go to **File** > **Preferences**.
2. In the **Additional Boards Manager URLs** field, paste the following URL:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. Click **OK**.
4. Go to **Tools** > **Board** > **Boards Manager...**
5. Search for `esp32` and install the package by **Espressif Systems**.

## 3. Install Required Libraries
The sketch is built on the **Maya library** in this repository, which in turn needs two third-party libraries.

1. Go to **Sketch** > **Include Library** > **Manage Libraries...**
2. Search for and install **WebSockets** by Markus Sattler (2.4 or newer).
3. Search for and install **ArduinoJson** by Benoit Blanchon — **version 6.x** (6.21 is what this was built against; 7.x is not supported).
4. Install the Maya library itself: copy the folder `hardware/libraries/Maya` from this repository into your Arduino libraries folder (`Documents/Arduino/libraries/` on Windows and macOS, `~/Arduino/libraries/` on Linux), so you end up with `.../libraries/Maya/library.properties`. Restart the Arduino IDE.

*(Note: WiFi, Preferences, BLE and ESP-NOW are built into the ESP32 core and do not need separate installation. Tested with the ESP32 core 2.0.17.)*

## 4. Open the Project
1. Open the Arduino IDE.
2. Go to **File** > **Open...**
3. Navigate to the `hardware/smartextension` directory and select `smartextension.ino`.

## 5. Select Your Board and Port
0. Set **Tools** > **Partition Scheme** to **Huge APP (3MB No OTA/1MB SPIFFS)**. BLE, TLS and Wi-Fi together are about 1.7 MB, which does not fit the default partition; without this the build stops with "Sketch too big".
   *(Building your own device? Use the [Maya library](../libraries/Maya/README.md) instead of this sketch.)*
1. Go to **Tools** > **Board** > **ESP32 Arduino**, and select your specific ESP32 board model (e.g., "DOIT ESP32 DEVKIT V1", "ESP32 Dev Module").
2. Connect your ESP32 to your computer using the USB cable.
3. Go to **Tools** > **Port**, and select the COM port (Windows) or `/dev/cu.usbserial...` (Mac/Linux) corresponding to your ESP32.

## 6. Flash the Firmware
1. Click the **Upload** button (the right-pointing arrow at the top left of the IDE).
2. Wait for the code to compile and upload. 
3. *Troubleshooting Tip:* If the upload gets stuck at `Connecting...`, you may need to hold down the **BOOT** button on your ESP32 board until the flashing process begins.

## 7. Verify Operation
1. Once the upload says "Done uploading", open the **Serial Monitor** (Tools > Serial Monitor).
2. Set the baud rate in the bottom right corner to **115200**.
3. You should see logs indicating the ESP32 is starting up.
4. If the device has no WiFi credentials saved, it will enter BLE provisioning mode and advertise as `Maya-` followed by its device id (for example `Maya-esp32-9f83b1c1`; the id is also printed on the Serial Monitor at boot). Use the Parent app's *Add device* screen to supply Wi-Fi credentials, the server URL and a PIN.
5. Every flash starts clean: saved Wi-Fi and PIN are wiped, so a freshly flashed board always begins in provisioning mode.
6. After provisioning the board reboots, joins your Wi-Fi and connects to the server. In the app it appears with three switches, drawn from what the board reports about itself.
