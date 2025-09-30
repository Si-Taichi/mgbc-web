Multi Ground Board Connecting-Website

Notes
   - Please always check your api url if it's the same you are going to use.
   - The data that send are said in the groundDashboard.py which consist of sensors data and status data, this includes : LIS331DLH sensor data, lc86g sensor, bme280 sensor and parachute deployment status which all combines to 11 data. 
   - If you want to see the csv data format, you can see it by running the program and check the in API server or checking the images that I have put in the images folder.

How to use (for testing with local websocket (ws_server.py) )

1. Download all the files and put it all inside a folder.
2. In terminal, cd to the location of the folder.
3. type : python run_api_system.py
4. ctrl + click on the dashboard ip to see the dashboard.
   - for seeing raw data and status sended ctrl + click on the API server ip.

How to use (Serial port)

1. Download the groundDashboard.py and config.py
2. Connect the board to serial port.
3. Go into config.py and change the mode, port and baudrate to match what you are using and save the file.
4. In terminal, cd to the location of the folder.
5. type : python groundDashboard.py
6. ctrl + click on the dashboard ip to see the dashboard.

Note :
##### To use only the dashboard simply only run only the groundDashboard.py with the config.py, so you can configure some of the variables that are use in the groundDashboard. #####
##### DO NOT make any changes while the dashboard is running, or else the dashboard will refresh itself and the data will be gone. Like staring the program again. It is        #####
##### recommended to run on the computer terminal not in the editor so that you don't accidently restart the dashborad.                                                         #####
