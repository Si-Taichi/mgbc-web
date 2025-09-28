Notes
   - Please always check your api url if it's the same you are going to use.
   - The data that send are said in the groundDashboard.py which consist of sensors data and status data, this includes : LIS331DLH sensor data, lc86g sensor, bme280 sensor and parachute deployment status which all combines to 11 data. 
   - If you want to see the gcs\all data format, you can see it by running the program and check the in API server.

How to use 

1. Download all the files and put it all inside a folder.
2. In terminal, cd to the location of the folder.
3. type : python run_api_system.py.
4. ctrl + click on the dashboard ip to see the dashboard.
   - for seeing raw data and status sended ctrl + click on the API server ip.

*note : to use only the dashboard simply only run only the groundDashboard.py on it's own.

Configurations
   - if you're testing without the api that you are going to use in the real work or real case you can config the numbers of boards, max data points and etc.
