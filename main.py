# Define Error Logging
def printerror(ex):
	print('\033[31m' + str(ex) + '\033[0m')

def printwarning(warn):
	print('\033[33m' + str(warn) + '\033[0m')

def printgreen(msg):
	print('\033[32m' + str(msg) + '\033[0m')

def printyellow(msg):
	print('\033[33m' + str(msg) + '\033[0m')

def printred(msg):
	print('\033[31m' + str(msg) + '\033[0m')

def printblue(msg):
	print('\033[34m' + str(msg) + '\033[0m')

def printblink(msg):
	print('\033[5m' + str(msg) + '\033[0m')

import os
if not os.geteuid() == 0:
	printerror("Please run this script with sudo.")
	exit(2)

print("Welcome to Microsoft Teams presence for Pi!")
print("Loading modules...")

try:
	import requests
	import socket
	import msal
	import atexit
	import os
	import os.path
	import argparse
	from random import randint
	import configparser
	from urllib.error import HTTPError
	import json
#	import unicornhat as unicorn
	import threading
	import sys
	import urllib.parse
	from time import sleep
	from datetime import datetime, time
	from signal import signal, SIGINT
#	from gpiozero import CPUTemperature
	import pyqrcode
except ModuleNotFoundError as ex:
	printerror("The app could not be started.")
	printerror("Please run 'sudo ./install.sh' first.")
	printerror(ex)
	exit(2)
except:
	printerror("An unknown error occured while loading modules.")
	exit(2)

# #############
# Define Var
version = 1.5
print("Booting v" + str(version))

config = configparser.ConfigParser()
if os.path.isfile(str(os.getcwd()) + "/azure_config.ini"):
	print("Reading config...")
	config.read("azure_config.ini")
	TENANT_ID = config["Azure"]["Tenant_Id"]
	CLIENT_ID = config["Azure"]["Client_Id"]
else:
	printwarning("Config does not exist, creating new file.")
	TENANT_ID = ""
	CLIENT_ID = ""
	while not TENANT_ID:
		TENANT_ID = input("Please enter your Azure tenant id: ")
	while not CLIENT_ID:
		CLIENT_ID = input("Please enter your Azure client id (or application ID): ")
	config["Azure"] = {"Tenant_Id": TENANT_ID, "Client_Id": CLIENT_ID}
	with open("azure_config.ini", "w") as configfile:
		config.write(configfile)

AUTHORITY = 'https://login.microsoftonline.com/' + TENANT_ID
ENDPOINT = 'https://graph.microsoft.com/v1.0'
SCOPES = [
    'User.Read',
    'Presence.Read'
]
workday_start = time(8)
workday_end = time(19)
workdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
width = 0
height = 0
blinkThread = None
after_work = False
globalRed = 0
globalGreen = 0
globalBlue = 0
token=''
points = []
fullname = ''
brightness_led = 0.5
sleepValue = 30 # seconds
# #############

# Check for arguments
parser = argparse.ArgumentParser()
parser.add_argument("--version", "-v", help="Prints the version", action="store_true")
parser.add_argument("--refresh", "-r", help="Sets the refresh value in seconds", type=int)
parser.add_argument("--brightness", "-b", help="Sets the brightness of the LED display. Value must be between 0.1 and 1", type=int)
parser.add_argument("--afterwork", "-aw", help="Check for presence after working hours", action="store_true")
parser.add_argument("--nopulse", "-np", help="Disables pulsing, if after work hours", action="store_true")
parser.add_argument("--weekend", "-w", help="Also checks on weekends", action="store_true")

args = parser.parse_args()
if args.version:
	print(str(version))
	exit(0)

if args.nopulse:
	printwarning("Option: No pulsing")

if args.refresh:
	if args.refresh < 10:
		printerror("Refresh value must be greater than 10")
		exit(4)
	sleep = args.refresh
	printwarning("Option: Sleep set to " + str(sleep))

if args.brightness:
	if args.brightness < 0.1 and args.brightness > 1:
		printerror("Value must be between 0.1 and 1")
		exit(5)
	brightness = args.brightness
	printwarning("Option: Brightness set to " + str(brightness))

if args.weekend:
	printwarning("Option: Set weekend checks to true")

if args.afterwork:
	printwarning("Option: Set after work to true")

#Handles Ctrl+C
def handler(signal_received, frame):
	# Handle any cleanup here
	print()
	printwarning('SIGINT or CTRL-C detected. Please wait until the service has stopped.')
	exit(0)

# Disable Printing
def blockPrint():
    sys.stdout = open(os.devnull, 'w')

# Restore Printing
def enablePrint():
    sys.stdout = sys.__stdout__

# Check times
def is_time_between(begin_time, end_time, check_time=None):
	# If check time is not given, default to current UTC time
	try:
		check_time = check_time or datetime.now().time()
		if begin_time < end_time:
			return check_time >= begin_time and check_time <= end_time
		else: # crosses midnight
			return check_time >= begin_time or check_time <= end_time
	except:
		printerror("Could not verify times. " + sys.exc_info()[0])
		return False
# Countdown for minutes
def countdown(t):
	total = t
	progvalue = 0
	while t:
		mins, secs = divmod(t, 60)
		timer = '{:02d}:{:02d}'.format(mins, secs)
		print("Time until next run: " + timer, end="\r")
		sleep(1)
		t -= 1
	print("                                      ", end="\r")


# Check or internet connection
def is_connected():
    try:
        # connect to the host -- tells us if the host is actually
        # reachable
        socket.create_connection(("www.google.com", 80))
        return True
    except OSError:
        pass
    return False

# Checks for updates
def checkUpdate():
	updateUrl = "https://raw.githubusercontent.com/petervirtech/teams_presence_recorder/master/doc/version"
	try:
		f = requests.get(updateUrl, timeout=10)
		latestVersion = float(f.text)
		if latestVersion > version:
			printwarning("There is an update available.")
			printwarning("Head over to https://github.com/petervirtech/teams_presence_recorder to get the latest features.")
		else:
			print("Application is running latest version.")
	except Exception as e:
		printerror("An error occured while searching for updates.")
		printerror(e)


##################################################

def Authorize():
	global token
	global fullname
	print("Starting authentication workflow.")
	try:
		cache = msal.SerializableTokenCache()
		if os.path.exists('token_cache.bin'):
			cache.deserialize(open('token_cache.bin', 'r').read())

		atexit.register(lambda: open('token_cache.bin', 'w').write(cache.serialize()) if cache.has_state_changed else None)

		app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

		accounts = app.get_accounts()
		result = None
		if len(accounts) > 0:
			result = app.acquire_token_silent(SCOPES, account=accounts[0])

		if result is None:
			# Create QR code
			qr = pyqrcode.create("https://microsoft.com/devicelogin")
			print(qr.terminal(module_color=0, background=231, quiet_zone=1))

			# Initiate flow
			flow = app.initiate_device_flow(scopes=SCOPES)
			if 'user_code' not in flow:
				raise Exception('Failed to create device flow')
			print(flow['message'])
			result = app.acquire_token_by_device_flow(flow)
			token = result['access_token']
			print("Aquired token")
			token_claim = result['id_token_claims']
			print("Welcome " + token_claim.get('name') + "!")
			fullname = token_claim.get('name')
			return True
		if 'access_token' in result:
			token = result['access_token']
			try:
				result = requests.get(f'{ENDPOINT}/me', headers={'Authorization': 'Bearer ' + result['access_token']}, timeout=5)
				result.raise_for_status()
				y = result.json()
				fullname = y['givenName'] + " " + y['surname']
				print("Token found, welcome " + y['givenName'] + "!")
				return True
			except requests.exceptions.HTTPError as err:
				if err.response.status_code == 404:
					printerror("MS Graph URL is invalid!")
					exit(5)
				elif err.response.status_code == 401:
					printerror("MS Graph is not authorized. Please reauthorize the app (401).")
					return False
			except requests.exceptions.Timeout as timeerr:
				printerror("The authentication request timed out. " + str(timeerr))
		else:
			raise Exception('no access token in result')
	except Exception as e:
		printerror("Failed to authenticate. " + str(e))
		sleep(2)
		return False

def printHeader():
	os.system('clear')
	print("============================================")
	print("            MSFT Teams Presence")
	print("============================================")
	print()

#Main
if __name__ == '__main__':
	# Tell Python to run the handler() function when SIGINT is recieved
	signal(SIGINT, handler)

	# Check internet
	if is_connected == False:
		printerror("No network. Please connect to the internet and restart the app.")
		exit(3)

	# Check for updates
	checkUpdate()

	trycount = 0
	while Authorize() == False:
		trycount = trycount +1
		if trycount > 10:
			printerror("Cannot authorize. Will exit.")
			exit(5)
		else:
			printwarning("Failed authorizing, empty token (" + str(trycount) + "/10). Will try again in 10 seconds.")
			Authorize()
			continue

	sleep(1)
	# Stop random blinking
	blinkThread.do_run = False
	blinkThread.join()

	trycount = 0

	while True:


		# Check network
		if is_connected() == False:
			printerror("No network is connected. Waiting for reconnect.")
			countdown(30)
			continue

		print("Fetching new data")
		headers={'Authorization': 'Bearer ' + token}

		jsonresult = ''

		try:
			result = requests.get(f'https://graph.microsoft.com/v1.0/me/presence', headers=headers, timeout=5)
			result.raise_for_status()
			jsonresult = result.json()

		except requests.exceptions.Timeout as timeerr:
			printerror("The request for Graph API timed out! " + str(timeerr))
			continue

		except requests.exceptions.HTTPError as err:
			if err.response.status_code == 404:
				printerror("MS Graph URL is invalid!")
				exit(5)
			elif err.response.status_code == 401:
				trycount = trycount + 1
				printerror("MS Graph is not authorized. Please reauthorize the app (401). Trial count: " + str(trycount))
				print()
				Authorize()
				continue

		except:
			print("Unexpected error:", sys.exc_info()[0])
			print("Will try again. Trial count: " + str(trycount))
			print()
			countdown(int(sleepValue))
			continue

		trycount = 0

		# Check for jsonresult
		if jsonresult == '':
			printerror("JSON result is empty! Will try again.")
			printerror(jsonresult)
			countdown(5)
			continue

		# Stop random blinking
		if blinkThread != None :
			blinkThread.do_run = False
			blinkThread.join()

		# Print to display
		os.system('clear')
		print("============================================")
		print("            MSFT Teams Presence")
		print("============================================")
		print()
		now = datetime.now()
		print("Last API call:\t\t" + now.strftime("%Y-%m-%d %H:%M:%S"))

		if args.brightness:
			printwarning("Option:\t\t\t" + "Set brightness to " + str(brightness))

		if args.refresh:
			printwarning("Option:\t\t\t" +  "Set refresh to " + str(sleepValue))

		if args.nopulse:
			printwarning("Option:\t\t\t" + "Pulsing disabled")

		if args.afterwork:
			printwarning("Option:\t\t\t" + "Set display after work to True")

		if args.weekend:
			printwarning("Option:\t\t\t" + "Set weekend checks to True")

		print("User:\t\t\t" + fullname)

		if jsonresult['activity'] == "Available":
			print("Teams presence:\t\t" + '\033[32m' + "Available" + '\033[0m')
		elif jsonresult['activity'] == "InACall":
			print("Teams presence:\t\t" + '\033[31m' + "In a call" + '\033[0m')
		elif jsonresult['activity'] == "Away":
			print("Teams presence:\t\t" + '\033[33m' + "Away" + '\033[0m')
		elif jsonresult['activity'] == "BeRightBack":
			print("Teams presence:\t\t" + '\033[33m' + "Be Right Back" + '\033[0m')
		elif jsonresult['activity'] == "Busy":
			print("Teams presence:\t\t" + '\033[31m' + "Busy" + '\033[0m')
		elif jsonresult['activity'] == "InAConferenceCall":
			print("Teams presence:\t\t" + '\033[31m' + "In a conference call" + '\033[0m')
		elif jsonresult['activity'] == "DoNotDisturb":
			print("Teams presence:\t\t" + '\033[31m' + "Do Not Disturb" + '\033[0m')
		elif jsonresult['activity'] == "Offline":
			print("Teams presence:\t\t" + "Offline")
		elif jsonresult['activity'] == "Inactive":
			print("Teams presence:\t\t" + '\033[33m' + "Inactive" + '\033[0m')
		elif jsonresult['activity'] == "InAMeeting":
			print("Teams presence:\t\t" + '\033[31m' + "In a meeting" + '\033[0m')
		elif jsonresult['activity'] == "OffWork":
			print("Teams presence:\t\t" + '\033[35m' + "Off work" + '\033[0m')
		elif jsonresult['activity'] == "OutOfOffice":
			print("Teams presence:\t\t" + '\033[35m' + "Out of office" + '\033[0m')
		elif jsonresult['activity'] == "Presenting":
			print("Teams presence:\t\t" + '\033[31m' + "Presenting" + '\033[0m')
		elif jsonresult['activity'] == "UrgentInterruptionsOnly":
			print("Teams presence:\t\t" + '\033[31m' + "Urgent interruptions only" + '\033[0m')
		else:
			print("Teams presence:\t\t" + "Unknown")
		print()
		countdown(int(sleepValue))