
import requests
import json
from datetime import datetime
import pytz
import json
from dotenv import load_dotenv
import os
import ssl
import asyncio
from aio_pika import connect, IncomingMessage, exceptions as aio_pika_exceptions


load_dotenv()

MAX_RETRIES = 10
INITIAL_RETRY_DELAY = 5

toronto_tz = pytz.timezone("America/Toronto")
ssl_context = ssl.create_default_context()

K2_LOGIN_URL = os.getenv("K2_LOGIN_URL")
K2_TRIAL_URL = os.getenv("K2_TRIAL_URL")
K2_SPOT_URL = os.getenv("K2_SPOT_URL")
K2_WALLET_URL = os.getenv("K2_WALLET_URL")

# Replace with K2 user account info
AUTO_TRADE = bool(os.getenv("AUTO_TRADE"))
TRIAL = os.getenv("TRIAL", "False").lower() in ("true", "1", "yes")
K2_USER_NAME = os.getenv("K2_USER_NAME")
K2_PASSWORD = os.getenv("K2_PASSWORD")

# Replace these with the rabbitmq information
RABBITMQ_HOST=os.getenv("RABBITMQ_HOST")
RABBITMQ_PORT=os.getenv("RABBITMQ_PORT")
RABBITMQ_USER=os.getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD=os.getenv("RABBITMQ_PASSWORD")
SIGNAL_MQ_NAME=os.getenv("SIGNAL_MQ_NAME")
RABBITMQ_URL= f"amqps://{RABBITMQ_USER}:{RABBITMQ_PASSWORD}@{RABBITMQ_HOST}/"


async def request(params):
    try:
        if params["type"] == "GET":  # Access dictionary keys using []
            response = requests.get(params["url"], headers=params["headers"])
            return response.json()
        elif params["type"] == "POST":
            print(params["url"])
            response = requests.post(params["url"], data=json.dumps(params["data"], indent=4), headers=params["headers"])
            return response.json()
    except requests.exceptions.Timeout:
        print("The request timed out.")
    except requests.exceptions.RequestException as e:
        print("An error occurred:", e)


async def k2_trade(signal):
    print("trading as: " + K2_USER_NAME)
    login_obj = {
        "url": K2_LOGIN_URL,
        "headers": {
            "Content-Type": "application/json"
        },
        "data": {
            "username": K2_USER_NAME,
            "password": K2_PASSWORD,
        },
        "type": "POST"
    }
    login_res = await request(login_obj)
    if(TRIAL):
        trial_obj = {
            "url": K2_TRIAL_URL,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": login_res["data"]["token"]
            },
            "type": "GET"
        }
        login_res = await request(trial_obj)
    
    wallet_obj = {
        "url": K2_WALLET_URL,
        "headers": {
            "Content-Type": "application/json",
            "Authorization": login_res["data"]["token"]
        },
        "type": "GET"
    }
    wallet_res = await request(wallet_obj)
    amount = float(wallet_res["data"]["spotAccountBalance"]) * float(signal["account_portion"])
    time_type = int(signal["time_type"])
    spot_trade_obj = {
        "url": K2_SPOT_URL,
        "headers": {
            "Content-Type": "application/json",
            "Authorization": login_res["data"]["token"]
        },
        "data": {
            "symbol": "1",
            "tradeType": signal["direction"],
            "seconds": time_type,
            "amount": amount,
            "expectTime": signal["epoc"]
        },
        "type": "POST"
    }
    trade_res = await request(spot_trade_obj)
    print(trade_res)


async def setup_rabbitmq():
    retry_count = 0
    retry_delay = INITIAL_RETRY_DELAY
    while True:
        try:
            print("Attempting to connect to RabbitMQ...")
            connection = await connect(RABBITMQ_URL)
            async with connection:
                print("Connected to RabbitMQ")
                channel = await connection.channel()
                # Declare the queue
                queue = await channel.declare_queue(SIGNAL_MQ_NAME)
                print(f"Waiting for messages from queue: {SIGNAL_MQ_NAME}. To exit, press CTRL+C.")
                # Start consuming messages
                await queue.consume(process_message)
                # Keep the consumer running
                await asyncio.Future()  # Prevent the connection from closing
        except aio_pika_exceptions.AMQPConnectionError:
            print("Connection to RabbitMQ failed or was closed. Retrying...")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        finally:
            retry_count += 1
            if retry_count > MAX_RETRIES:
                print("Max retries reached. Exiting...")
                break
            print(f"Retrying connection in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # Exponential backoff with a maximum delay


async def process_message(message: IncomingMessage):
    try:
        data = json.loads(message.body.decode())
        await k2_trade(data)  # Assuming this is a user-defined function
        async with message.process():
            print(f"Processed message: {message.body.decode()}")
    except Exception as e:
        print(f"Error processing message: {e}")
        # Optionally handle the message differently or log for debugging


async def main():
    await setup_rabbitmq()
    
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")
