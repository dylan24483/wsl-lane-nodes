#!/usr/bin/env python3
from gpiozero import Button, LED
from signal import pause
from time import sleep

BALL_DETECT = Button(17, pull_up=True, bounce_time=0.05)
PINSETTER_CYCLE = LED(27)

def on_ball_detected():
    print("Ball detected! Pulsing mock cycle relay...")
    PINSETTER_CYCLE.on()
    sleep(0.15)
    PINSETTER_CYCLE.off()

BALL_DETECT.when_pressed = on_ball_detected

print("Lane node test running. Press button to simulate ball-detect. Ctrl+C to exit.")
pause()
