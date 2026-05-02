#!/usr/bin/env python3
from gpiozero import Button, LED
from time import sleep

print("== Step A: testing LED output ==")
led = LED(27)
print("LED ON for 2 seconds...")
led.on()
sleep(2)
led.off()
print("LED OFF.")

print("== Step B: polling button state for 30 seconds ==")
print("Press and hold the button intermittently.")
button = Button(17, pull_up=True)

try:
    for i in range(60):
        state = "PRESSED" if button.is_pressed else "released"
        print(f"  [{i:02d}] GPIO 17: {state}")
        sleep(0.5)
except KeyboardInterrupt:
    pass

print("Done.")
