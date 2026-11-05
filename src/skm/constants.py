"""Protocol constants, RE'd from CKM2PO.exe (Ghidra) 2026-11.

Evidence map (Ghidra addresses):
  TX buffer      DAT_0059e764   (command frame built here byte-by-byte)
  RX buffer      DAT_00596764   (65536 bytes, filled by FT_Read drain)
  RX count       DAT_00596760
  error sentinel 0x499602D2 (= 1234567890 decimal — "status code" returned
                 by TOTAL layer when FT_* status != 0)
"""

# transport ---------------------------------------------------------------
SENTINEL = 0x499602D2        # FUN_0058a258: "exchange failed" marker
RX_BUFSZ = 0x10000           # FUN_00589164 reads at most 65536 bytes
TX_BUFSZ = 14                # longest frame: 'H' + 10 payload bytes ('aadc')

# baud from DRIVER i386 build / FUN_00589474 (RS-232 variant sets it too)
BAUD = 9600

# discovery (FUN_00570b84): open by description, serial hardcoded
DEVICE_DESCRIPTIONS = {
    3: ["CKM 23v1", "CKM 23v2", "CKM 23v3", "CKM 23v3RS"],   # version flag 3
    1: ["CKM 21v1", "CKM 21v2"],                            # version flag 1
}
DEVICE_SERIAL = "12345678"

# single-byte commands ----------------------------------------------------
CMD_KEEPALIVE = "A"       # FUN_005894b8/00589630/005897a8: A -> poll up to 51
                          #   retries until 7 reply bytes collected
CMD_F_QUERY = "F"         # FUN_00589904: F -> 2-byte reply parsed to double
                          # FUN_0058a6d4: F -> 3-byte echo reply [F,b1,b2]
CMD_MEASURE_START = "N"   # FUN_00589aec: N -> continuous byte stream until
                          #   65536 captured or 100 consecutive empty polls,
                          #   then app sends 'S'
CMD_MEASURE_STOP = "S"
CMD_CH_X = "X"            # FUN_00589f6c: param 1 -> 'X' (no reply)
CMD_CH_Y = "Y"            #             param 2/4 -> 'Y'
CMD_SET = {1: "I", 2: "B", 3: "C", 4: "D", 5: "E"}   # FUN_0058a024: no reply
CMD_QUERY = "Q"           # FUN_0058a10c: Q -> 1-byte reply (101 polls)
CMD_RANGE = "R"           # FUN_0058a3a8: R + '0'/'1'/'2' (no reply, ret 0/3)
CMD_SPEAKER_OFF = "U"     # FUN_0058a440: U/V -> 1-byte reply (1001 polls)
CMD_SPEAKER_ON = "V"
CMD_SET_REPLY = {1: "M", 2: "B", 3: "C", 4: "D", 5: "E"}  # FUN_0058a818:
                          # 1-byte reply (101 polls)
CMD_SAMPLE = "J"          # FUN_0058a988: J -> [J,hi,lo] 12-bit (0xFF hi -> 0)
CMD_GENERATOR = "H"       # FUN_0058aadc: H + 10-byte payload (11 total), no
                          #   direct reply; app then sends 'I' and expects
                          #   6 reply bytes (≤101 polls)

# retry budgets observed (empty poll loops, before "no reply" verdict)
RETRY_KEEPALIVE = 0x33    # 51
RETRY_SET_REPLY = 0x65    # 101  (M/B/C/D/E, Q, F-query, speaker uses 0x3E9)
RETRY_SPEAKER = 0x3E9     # 1001
RETRY_F_READ = 0x65
RETRY_J_READ = 0x65
RETRY_MEASURE_IDLE = 0x65  # 100 consecutive empty polls stop capture
MEASURE_WRAP = 0x10000     # capture wraps at 65536 samples

# generator frame layout (FUN_0058aadc): indices into TX buffer
#  0:'H' 1:p2 2:p1 3-4:div16(+/-1 guard,0->1) 5:2 6:p7 7:p6 8:p5 9-10:div16
GEN_DIV_HI = 3
GEN_DIV_LO = 4
