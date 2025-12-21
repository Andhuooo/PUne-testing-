#!/usr/bin/env python3
# efuse_full_monitor_raw.py
# MP5922 PMBus full monitor with RAW + converted values

from usb_iss import UsbIss
import time
import sys

# =========================
# CONFIGURATION
# =========================
PORT = "/dev/ttyACM0"
I2C_SPEED_KHZ = 100
MP5922_ADDR = 0x70

PAGES = {
    0: "Main Rail (Loop 1)",
    1: "Aux Rail  (Loop 2)",
    2: "Rail 3    (Loop 3)"
}

# =========================
# LOW-LEVEL HELPERS
# =========================
def read_word(i2c, addr, reg):
    d = i2c.read(addr, reg, 2)
    return d[0] | (d[1] << 8)

def write_word(i2c, addr, reg, value):
    i2c.write(addr, reg, [value & 0xFF, (value >> 8) & 0xFF])

def write_byte(i2c, addr, reg, value):
    i2c.write(addr, reg, [value & 0xFF])

def select_page(i2c, page):
    i2c.write(MP5922_ADDR, 0x00, [page & 0xFF])
    time.sleep(0.01)

# =========================
# PMBUS CORE ACTIONS
# =========================
def unlock_mp5922(i2c):
    # PMBus password
    write_word(i2c, MP5922_ADDR, 0xE1, 0x82C2)
    time.sleep(0.02)

def clear_faults(i2c):
    # CLEAR_FAULTS
    i2c.write(MP5922_ADDR, 0x03, [])
    time.sleep(0.01)

def rail_enable(i2c, page):
    select_page(i2c, page)
    write_byte(i2c, MP5922_ADDR, 0x01, 0x80)

def rail_disable(i2c, page):
    select_page(i2c, page)
    write_byte(i2c, MP5922_ADDR, 0x01, 0x00)

# =========================
# DATASHEET CONVERSIONS
# =========================
def raw_to_voltage(raw):
    # READ_VIN / READ_VOUT
    # 15.625 mV per LSB
    return raw * 0.015625

def raw_to_power(raw):
    # READ_POUT / READ_PIN
    # 1/256 W per LSB
    return raw * 0.125

# =========================
# FAULT DECODER
# =========================
def decode_faults(sw, si, sin, st):
    faults = []

    # STATUS_WORD (0x79)
    if sw & (1 << 15): faults.append("VOUT_OV")
    if sw & (1 << 14): faults.append("IOUT_OC")
    if sw & (1 << 13): faults.append("VIN_UV")
    if sw & (1 << 12): faults.append("TEMP_FAULT")
    if sw & (1 << 7):  faults.append("DEVICE_FAULT")
    if sw & (1 << 6):  faults.append("POWER_GOOD=NO")

    # STATUS_IOUT (0x7B)
    if si & 0x01: faults.append("IOUT_OC_WARNING")
    if si & 0x02: faults.append("IOUT_OC_FAULT")

    # STATUS_INPUT (0x7C)
    if sin & 0x01: faults.append("VIN_UV_FAULT")
    if sin & 0x02: faults.append("VIN_OV_FAULT")

    # STATUS_TEMP (0x7D)
    if st & 0x01: faults.append("TEMP_WARNING")
    if st & 0x02: faults.append("TEMP_FAULT")

    return faults if faults else ["NO_FAULTS"]

# =========================
# STATUS DISPLAY
# =========================
def show_status(i2c):
    print("\n=========== MP5922 STATUS (RAW + CONVERTED) ===========\n")

    # -------- GLOBAL INPUT POWER --------
    pin_raw = read_word(i2c, MP5922_ADDR, 0x97)
    pin_w   = raw_to_power(pin_raw)

    print("INPUT (GLOBAL)")
    print(f"  READ_PIN : raw=0x{pin_raw:04X} ({pin_raw}) → {pin_w:.2f} W\n")

    total_pout = 0.0

    # -------- PER RAIL --------
    for page, name in PAGES.items():
        select_page(i2c, page)

        vin_raw  = read_word(i2c, MP5922_ADDR, 0x88)
        vout_raw = read_word(i2c, MP5922_ADDR, 0x8B)
        iout_raw = read_word(i2c, MP5922_ADDR, 0x8C)   # diagnostic only
        pout_raw = read_word(i2c, MP5922_ADDR, 0x96)

        sw  = read_word(i2c, MP5922_ADDR, 0x79)
        si  = read_word(i2c, MP5922_ADDR, 0x7B)
        sin = read_word(i2c, MP5922_ADDR, 0x7C)
        st  = read_word(i2c, MP5922_ADDR, 0x7D)

        vin  = raw_to_voltage(vin_raw)
        vout = raw_to_voltage(vout_raw)
        pout = raw_to_power(pout_raw)

        # ✅ Correct current (derived, not scaled)
        iout = pout / vout if vout > 0 else 0.0

        total_pout += pout
        faults = decode_faults(sw, si, sin, st)

        print(f"PAGE {page} : {name}")
        print(f"  VIN   : raw=0x{vin_raw:04X} ({vin_raw}) → {vin:.2f} V")
        print(f"  VOUT  : raw=0x{vout_raw:04X} ({vout_raw}) → {vout:.2f} V")
        print(f"  IOUT  : {iout:.3f} A (derived from POUT/VOUT)")
        print(f"           raw=0x{iout_raw:04X} ({iout_raw}) [diagnostic]")
        print(f"  POUT  : raw=0x{pout_raw:04X} ({pout_raw}) → {pout:.2f} W")
        print(f"  FAULTS: {', '.join(faults)}\n")

    # -------- SUMMARY --------
    loss = pin_w - total_pout
    eff  = (total_pout / pin_w * 100) if pin_w > 0 else 0

    print("POWER SUMMARY")
    print(f"  ΣPOUT     : {total_pout:.2f} W")
    print(f"  PIN       : {pin_w:.2f} W")
    print(f"  LOSSES    : {loss:.2f} W")
    print(f"  EFFICIENCY: {eff:.2f} %")
    print("\n=====================================================\n")

# =========================
# MAIN / CLI
# =========================
def main():
    iss = UsbIss()
    iss.open(PORT)
    iss.setup_i2c(I2C_SPEED_KHZ)
    i2c = iss.i2c

    unlock_mp5922(i2c)

    if len(sys.argv) < 2:
        print("""
Usage:
  python efuse_full_monitor_raw.py status
  python efuse_full_monitor_raw.py on <page>
  python efuse_full_monitor_raw.py off <page>
  python efuse_full_monitor_raw.py on_all
  python efuse_full_monitor_raw.py off_all
  python efuse_full_monitor_raw.py clear
""")
        iss.close()
        return

    cmd = sys.argv[1]

    if cmd == "status":
        show_status(i2c)

    elif cmd == "on":
        rail_enable(i2c, int(sys.argv[2]))

    elif cmd == "off":
        rail_disable(i2c, int(sys.argv[2]))

    elif cmd == "on_all":
        for p in PAGES:
            rail_enable(i2c, p)

    elif cmd == "off_all":
        for p in PAGES:
            rail_disable(i2c, p)

    elif cmd == "clear":
        clear_faults(i2c)
        print("[OK] Faults cleared")

    else:
        print("Unknown command")

    iss.close()

if __name__ == "__main__":
    main()
