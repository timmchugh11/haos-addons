/*
  ESP32-C6 MeshCore serial simulator

  This is not MeshCore firmware. It is a small Arduino sketch that emulates
  enough of the MeshCore Companion serial protocol for meshcore_py and the
  MeshCore GUI add-on to connect, load device info, discover one channel,
  load an empty contacts list, and poll messages.

  Board target:
    ESP32-C6-WROOM-1 / ESP32-C6 Dev Module

  Arduino IDE notes:
    - Enable "USB CDC On Boot" if your ESP32-C6 board exposes native USB.
    - Use 115200 baud in the add-on.
    - Select the serial port exposed by this board in Home Assistant.

  Host frame format:
    '<' uint16_le(payload_length) payload

  Device responses use the same framing. The payload's first byte is the
  MeshCore response packet type expected by meshcore_py.
*/

#include <Arduino.h>

#ifndef LED_BUILTIN
#define LED_BUILTIN 8
#endif

static const uint8_t FRAME_MARKER = 0x3c;

static uint8_t publicKey[32] = {
  0x21, 0x32, 0x43, 0x54, 0x65, 0x76, 0x87, 0x98,
  0xa9, 0xba, 0xcb, 0xdc, 0xed, 0xfe, 0x0f, 0x10,
  0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
  0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x01,
};

static uint8_t publicChannelSecret[16] = {
  0x8d, 0x31, 0x25, 0x6f, 0x35, 0x3e, 0xaa, 0xa0,
  0x71, 0x7f, 0x4b, 0x91, 0x45, 0x49, 0x26, 0x34,
};

enum RxState {
  WAIT_MARKER,
  READ_LEN_0,
  READ_LEN_1,
  READ_PAYLOAD,
};

static RxState rxState = WAIT_MARKER;
static uint16_t rxLen = 0;
static uint16_t rxPos = 0;
static uint8_t rxPayload[512];

static void writeU16LE(uint8_t *buf, size_t &pos, uint16_t value) {
  buf[pos++] = value & 0xff;
  buf[pos++] = (value >> 8) & 0xff;
}

static void writeU32LE(uint8_t *buf, size_t &pos, uint32_t value) {
  buf[pos++] = value & 0xff;
  buf[pos++] = (value >> 8) & 0xff;
  buf[pos++] = (value >> 16) & 0xff;
  buf[pos++] = (value >> 24) & 0xff;
}

static void writeI32LE(uint8_t *buf, size_t &pos, int32_t value) {
  writeU32LE(buf, pos, (uint32_t)value);
}

static void writePaddedString(uint8_t *buf, size_t &pos, const char *value, size_t width) {
  size_t i = 0;
  for (; i < width && value[i] != '\0'; i++) {
    buf[pos++] = (uint8_t)value[i];
  }
  for (; i < width; i++) {
    buf[pos++] = 0;
  }
}

static void sendFrame(const uint8_t *payload, uint16_t len) {
  Serial.write(FRAME_MARKER);
  Serial.write((uint8_t)(len & 0xff));
  Serial.write((uint8_t)((len >> 8) & 0xff));
  Serial.write(payload, len);
  Serial.flush();
}

static void sendOk() {
  uint8_t payload[] = {0x00};
  sendFrame(payload, sizeof(payload));
}

static void sendError(uint8_t code = 1) {
  uint8_t payload[] = {0x01, code};
  sendFrame(payload, sizeof(payload));
}

static void sendSelfInfo() {
  uint8_t payload[128];
  size_t pos = 0;

  payload[pos++] = 0x05;       // SELF_INFO
  payload[pos++] = 0x01;       // adv_type
  payload[pos++] = 10;         // tx_power
  payload[pos++] = 22;         // max_tx_power
  memcpy(payload + pos, publicKey, sizeof(publicKey));
  pos += sizeof(publicKey);
  writeI32LE(payload, pos, 51500000);     // adv_lat 51.5
  writeI32LE(payload, pos, -140000);      // adv_lon -0.14
  payload[pos++] = 1;          // multi_acks
  payload[pos++] = 0;          // adv_loc_policy
  payload[pos++] = 0;          // telemetry mode bits
  payload[pos++] = 0;          // manual_add_contacts false
  writeU32LE(payload, pos, 869525);       // radio_freq kHz units expected /1000
  writeU32LE(payload, pos, 250);          // radio_bw kHz units expected /1000
  payload[pos++] = 11;         // radio_sf
  payload[pos++] = 5;          // radio_cr

  const char *name = "ESP32C6 MeshCore Sim";
  while (*name) {
    payload[pos++] = (uint8_t)*name++;
  }

  sendFrame(payload, pos);
}

static void sendDeviceInfo() {
  uint8_t payload[128];
  size_t pos = 0;

  payload[pos++] = 0x0d;       // DEVICE_INFO
  payload[pos++] = 3;          // fw ver, reader parses extended fields when >= 3
  payload[pos++] = 50;         // max_contacts = value * 2
  payload[pos++] = 8;          // max_channels
  writeU32LE(payload, pos, 123456);
  writePaddedString(payload, pos, "sim-20260507", 12);
  writePaddedString(payload, pos, "ESP32-C6-WROOM-1 simulator", 40);
  writePaddedString(payload, pos, "sim-1.0.0", 20);

  sendFrame(payload, pos);
}

static void sendChannelInfo(uint8_t idx) {
  if (idx != 0) {
    sendError(2);
    return;
  }

  uint8_t payload[1 + 1 + 32 + 16];
  size_t pos = 0;

  payload[pos++] = 0x12;       // CHANNEL_INFO
  payload[pos++] = 0;          // channel_idx
  writePaddedString(payload, pos, "Public", 32);
  memcpy(payload + pos, publicChannelSecret, sizeof(publicChannelSecret));
  pos += sizeof(publicChannelSecret);

  sendFrame(payload, pos);
}

static void sendEmptyContacts() {
  uint8_t start[5];
  size_t pos = 0;
  start[pos++] = 0x02;         // CONTACT_START
  writeU32LE(start, pos, 0);   // contact count
  sendFrame(start, pos);

  uint8_t end[5];
  pos = 0;
  end[pos++] = 0x04;           // CONTACT_END
  writeU32LE(end, pos, millis() / 1000);
  sendFrame(end, pos);
}

static void sendNoMoreMessages() {
  uint8_t payload[] = {0x0a};  // NO_MORE_MSGS
  sendFrame(payload, sizeof(payload));
}

static void sendPrivateKeyDisabled() {
  uint8_t payload[] = {0x0f};  // DISABLED
  sendFrame(payload, sizeof(payload));
}

static void sendBattery() {
  uint8_t payload[11];
  size_t pos = 0;
  payload[pos++] = 0x0c;       // BATTERY
  writeU16LE(payload, pos, 4100);
  writeU32LE(payload, pos, 64);
  writeU32LE(payload, pos, 1024);
  sendFrame(payload, pos);
}

static void sendCurrentTime() {
  uint8_t payload[5];
  size_t pos = 0;
  payload[pos++] = 0x09;       // CURRENT_TIME
  writeU32LE(payload, pos, millis() / 1000);
  sendFrame(payload, pos);
}

static void handleCommand(const uint8_t *cmd, uint16_t len) {
  if (len == 0) {
    return;
  }

  switch (cmd[0]) {
    case 0x01:                 // appstart: 01 03 "      mccli"
      sendSelfInfo();
      break;

    case 0x16:                 // device query
      sendDeviceInfo();
      break;

    case 0x1f:                 // get channel
      sendChannelInfo(len > 1 ? cmd[1] : 0);
      break;

    case 0x04:                 // get contacts
      sendEmptyContacts();
      break;

    case 0x17:                 // export private key
      sendPrivateKeyDisabled();
      break;

    case 0x0a:                 // get next message
      sendNoMoreMessages();
      break;

    case 0x14:                 // battery
      sendBattery();
      break;

    case 0x05:                 // get time
      sendCurrentTime();
      break;

    case 0x07:                 // send advert
    case 0x08:                 // set name
    case 0x0e:                 // set coords
    case 0x20:                 // set channel
    case 0x25:                 // set device PIN
    case 0x29:                 // set custom var
    case 0x3a:                 // set autoadd config
      sendOk();
      break;

    case 0x28: {               // get custom vars
      uint8_t payload[] = {0x15};
      sendFrame(payload, sizeof(payload));
      break;
    }

    case 0x3b: {               // get autoadd config
      uint8_t payload[] = {0x19, 0x00};
      sendFrame(payload, sizeof(payload));
      break;
    }

    default:
      sendError(0xff);
      break;
  }
}

static void pollSerialFrames() {
  while (Serial.available() > 0) {
    uint8_t b = Serial.read();

    switch (rxState) {
      case WAIT_MARKER:
        if (b == FRAME_MARKER) {
          rxLen = 0;
          rxPos = 0;
          rxState = READ_LEN_0;
        }
        break;

      case READ_LEN_0:
        rxLen = b;
        rxState = READ_LEN_1;
        break;

      case READ_LEN_1:
        rxLen |= ((uint16_t)b << 8);
        if (rxLen == 0 || rxLen > sizeof(rxPayload)) {
          rxState = WAIT_MARKER;
        } else {
          rxPos = 0;
          rxState = READ_PAYLOAD;
        }
        break;

      case READ_PAYLOAD:
        rxPayload[rxPos++] = b;
        if (rxPos >= rxLen) {
          handleCommand(rxPayload, rxLen);
          rxState = WAIT_MARKER;
        }
        break;
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);

  // Give native USB CDC a short moment to enumerate.
  delay(500);
}

void loop() {
  pollSerialFrames();

  static uint32_t lastBlink = 0;
  if (millis() - lastBlink > 1000) {
    lastBlink = millis();
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}
