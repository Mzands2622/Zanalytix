import requests

# Replace with the correct localhost URL for your function
url = 'http://localhost:7071/api/translation_queuing_trigger'

try:
    # Send a POST request to the trigger
    response = requests.post(url)

    # Print the status code and response content
    if response.status_code == 200:
        print("Success! Translation trigger fired.")
        print("Response:", response.text)
    else:
        print(f"Failed! Status Code: {response.status_code}")
        print("Response:", response.text)

except Exception as e:
    print(f"Error triggering translation function: {e}")
