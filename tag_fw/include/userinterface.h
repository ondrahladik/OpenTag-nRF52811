#ifndef _UI_H_
#define _UI_H_
#include <Arduino.h>
#include <stdint.h>

void addOverlay();

void afterFlashScreenSaver();
void showSplashScreen();
void showAPFound();
void showNoAP();
void showLongTermSleep();
void showNoEEPROM();

extern const uint8_t fwVersionMajor;
extern const uint8_t fwVersionMinor;
extern const uint8_t fwVersionPatch;
extern bool lowBatteryShown;
extern bool noAPShown;

#endif