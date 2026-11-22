#https://github.com/plemaster01/PyDuino/blob/828b4df7c2a53debfbe7e4a1013ebe74e77b71e2/main.py
#this wont work with my macbook

# pip install pyserial
import serial.tools.list_ports

ports = serial.tools.list_ports.comports()
serialInst = serial.Serial()
portsList = []

for one in ports:
    portsList.append(str(one))
    print(str(one))

com = input("Select Com Port for Arduino #: ")

for i in range(len(portsList)):
    if portsList[i].startswith("COM" + str(com)): # mac needs a devise path for example: use = "/dev/tty.usbmodem1101"
        use = "COM" + str(com)
        print(use)

serialInst.baudrate = 9600
serialInst.port = use
serialInst.open()

while True:
    command = input("Arduino Command (ON/OFF/exit): ")
    serialInst.write(command.encode('utf-8'))

    if command == 'exit':
        exit()