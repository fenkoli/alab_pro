import serial.tools.list_ports

## Forming connection with Arduino ##

#def creating_ard_connection(): #Original from the tutorial, that we tested earlier
#    ports = serial.tools.list_ports.comports()
#    con = serial.Serial()
#
#    #loop for gettiing the right port
#    portsList = []
#
#    for one in ports:
#        portsList.append(str(one))
#        print(str(one))
#
#    com = input("Select Com Port for Arduino #: ")
#
#    for i in range(len(portsList)):
#        if portsList[i].startswith("COM" + str(com)): # masc needs a devise path for example: use = "/dev/tty.usbmodem1101"
#            use = "COM" + str(com)
#            print(use)
#
#    #connection is created here
#    con.baudrate = 9600
#    con.port = use
#    con.open()
#
#    return con

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
    con.port = ports[int(com)].device  #Should on macOS and Windows
    con.open()

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


def read_result(connection):
    #Takes only the RGB line
    while True:
        line = connection.readline().decode("ascii", "ignore").strip()
        if line.startswith("RGB "):
            print(line)
            result = [int(value) for value in line.split()[1:]] #Turns RGB values to int list
            return result

def save_results(receipe, rgb):
    #Here we can save results to csv or what ever
    #I will just print them for now
    print(receipe)
    print(rgb)

def loop():
    con = creating_ard_connection()

    while True:
        start_cycle()
        pump_seconds = get_pump_seconds()
        sent_seconds(con, pump_seconds)
        result = read_result(con)
        save_result(pump_seconds, result)


loop()











