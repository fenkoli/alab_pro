import serial.tools.list_ports
import csv
import time
from pathlib import Path

## Forming connection with Arduino ##

def creating_ard_connection():
    ports = serial.tools.list_ports.comports()
    con = serial.Serial()

    #loop for gettiing the right port
    for i, one in enumerate(ports):   #print an index for selection
        print(i, str(one))

    com = input("Select port number: ")  #prompt for the list index

    #connection is created here
    con.baudrate = 9600
    con.timeout = 1 #  con.read results withou /n will get stuck without this
    con.port = ports[int(com)].device  #Should work with macOS and Windows
    con.open()
    time.sleep(2) #Arduino resets when the port opens, wait for the bootloader

    return con

def get_pump_seconds():
    #This is the place for generating the new receipt for color mixture with ML or some other logic.
    #To be finished later, the values are hard coded for now.
    pumping_time = [800, 800, 700, 700] #times for the pumps. 3000 milliseconds in total (correspond to cuvette volume)
    return pumping_time


def start_cycle():
    #Starts the loop. A placeholder for the robot arm automation.
    while True:
        command = str(input('To start cycle write "S" to exit write "E": '))
        if command == "S":
            return
        if command == "E":
            exit()
        else:
            print("Unknown command, try again.")

def sent_seconds(connection, pump_instructions):
    pump_times = " ".join(str(time) for time in pump_instructions) # Arduoino takes a string "RUN 800 800 700 700"
    connection.write(f"RUN {pump_times}\n".encode("ascii")) #sends pumping times (ms) to arduino 

def read_line(connection):
    #One line from Arduino as text. Empty string if nothing came within 1 second.
    return connection.readline().decode("ascii", "ignore").strip()

def read_until(connection, prefix):
    #Reads and drops lines until one starts with prefix, then returns it.
    while True:
        line = read_line(connection)
        if line.startswith(prefix):
            return line

def read_result(connection):
    #Takes only the RGB line
    line = read_until(connection, "RGB ")
    print(line)
    result = [int(value) for value in line.split()[1:]] #Turns RGB values to int list
    return result

def initialize(connection):
    flush_ms = [1000, 1000, 1000, 0]

    input("Press enter to flush pump lines: ") # time to prepare the flush
    sent_seconds(connection, flush_ms)
    read_until(connection, "DONE") # wait until the flush is done
    print("Flush done.")

    input("Place the calibration reference, then press Enter to calibrate: ") #waiting time
    connection.write(b"CAL\n")
    read_until(connection, "CAL DONE")
    print("Calibration done.")

def save_result(pump_ms, rgb_result):
    filepath = Path(__file__).resolve().parent / "data" / "results.csv"

    filepath.parent.mkdir(parents=True, exist_ok=True)
    file_exists = filepath.exists()

    with open(filepath, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["t1_ms", "t2_ms", "t3_ms", "t4_ms", "r", "g", "b"])
        writer.writerow([*pump_ms, *rgb_result])

def loop():
    con = creating_ard_connection()
    initialize(con)

    while True:
        start_cycle()
        pump_seconds = get_pump_seconds()
        sent_seconds(con, pump_seconds)
        read_until(con, "DONE")
        input("Pumping done. Press Enter to measure: ")
        con.write(b"GO\n")
        result = read_result(con)
        save_result(pump_seconds, result)

loop()
