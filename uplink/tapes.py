"""Holotapes that ship with the terminal (text only)."""

BUILTIN_TAPES = [
    {"id": "builtin-build-log", "name": "BUILD LOG 01", "secs": 46, "builtin": True, "lines": [
        "LOG ENTRY. FELIX RECORDING.", "THE UPLINK RACK IS COMING TOGETHER.", "THREE THINKCENTRES ON THEIR SHELVES.",
        "PVE-1 ROUTES. PVE-2 PLAYS. PVE-3 REMEMBERS.", "THE CONTROL PANEL PRINT CAME OUT CLEAN.",
        "ESP32 READS THE VPN SWITCH NOW.", "NEXT: WIRE THE STANDBY LAMP.", "END LOG."]},
    {"id": "builtin-venue", "name": "VENUE CHECKLIST", "secs": 38, "builtin": True, "lines": [
        "ARRIVAL PROCEDURE. LISTEN CAREFULLY.", "ONE. FIND THE VENUE RJ45. PLUG INTO WAN.",
        "TWO. FLIP MAIN POWER. WAIT FOR PVE-1.", "THREE. SELECT TUNNEL. TAILSCALE OR TWINGATE.",
        "FOUR. CHECK THE LAMPS. GREEN MEANS GO.", "FIVE. START THE STREAM.", "END OF PROCEDURE."]},
    {"id": "builtin-late", "name": "LATE SESSION", "secs": 52, "builtin": True, "lines": [
        "IT IS 03:12. STUDIO IS QUIET.", "THE KICK FINALLY SITS RIGHT.", "TUNED IT DOWN A SEMITONE. MORE WEIGHT.",
        "PSY LEAD NEEDS LESS RESONANCE.", "BOUNCED THE STEMS TO PVE-3.",
        "IF YOU FIND THIS TAPE, PLAY THE DROP LOUD.", "SIGNING OFF."]},
]
