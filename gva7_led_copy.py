# Google Gemini-Powered Voice Assistant
#  
# Tested and working on Raspberry Pi 4   
# By TechMakerAI on YouTube
#  

from datetime import date
from io import BytesIO
import threading
import queue
import time
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

import google.generativeai as genai
from gtts import gTTS
from gpiozero import LED
 
from pygame import mixer 
import speech_recognition as sr

import sounddevice

import json
import requests  # Added to make HTTP requests

# Using Raspberry Pi's 3.3v GPIO pins 24 and 25 for LEDs
gled = LED(24) 
rled = LED(25)

mixer.pre_init(frequency=24000, buffer=2048) 
mixer.init()

# add Google Gemini API key here
my_api_key = "AIzaSyDd4T3Cq8UaH4kBpNdrqMA2sxn3NpbF-nI"

if len(my_api_key) < 2:
    print(f"Please add your Google Gemini API key in the program (line 36). \n " )
    quit() 

genai.configure(api_key= my_api_key)

model = genai.GenerativeModel('gemini-pro',
    generation_config=genai.GenerationConfig(
        candidate_count=1,
        top_p = 0.95,
        top_k = 64,
        max_output_tokens=100,
        temperature = 0.9,
    ))

chat = model.start_chat(history=[])

today = str(date.today())

numtext = 0 
numtts = 0 
numaudio = 0

def chatfun(request, text_queue, llm_done, stop_event):
    global numtext, chat
    
    response = chat.send_message(request, stream=True)
    
    shortstring = ''  
    ctext = ''
    
    for chunk in response:
        try:
            if chunk.candidates[0].content.parts:
                ctext = chunk.candidates[0].content.parts[0].text
                ctext = ctext.replace("*", "")
                
                if len(shortstring) > 10 or len(ctext) >10:
            
                    shortstring = "".join([shortstring, ctext])
                    
                    text_queue.put( shortstring )
            
                    print(shortstring, end='') #, flush=True)
                    shortstring = ''
                    ctext = ''
                    # time.sleep(0.2)
                    numtext += 1
            
                else:
                    shortstring = "".join([shortstring, ctext])
                    ctext = ''
                
        except Exception as e:
            continue 

    if len(ctext) > 0: 
        shortstring = "".join([shortstring, ctext])
        
    if len(shortstring) > 0: 
        print(shortstring, end='') 
        
        text_queue.put(shortstring)                         
    
        numtext += 1
        
    if numtext > 0: 
        append2log(f"AI: {response.candidates[0].content.parts[0].text } \n")
        
    else:
        llm_done.set()
        stop_event.set()
    
    llm_done.set()

def speak_text(text):
    global slang, rled
           
    mp3file = BytesIO()
    tts = gTTS(text, lang = "en", tld = 'us') 
    tts.write_to_fp(mp3file)

    mp3file.seek(0)
    rled.on()
    print("AI: ", text)
    
    try:
        mixer.music.load(mp3file, "mp3")
        mixer.music.play()

        while mixer.music.get_busy():
            time.sleep(0.2)   

    except KeyboardInterrupt:
        mixer.music.stop()
        mp3file = None
        rled.off() 

    mp3file = None

    rled.off() 
  
# thread 2 for tts    
def text2speech(text_queue, tts_done, llm_done, audio_queue, stop_event):

    global numtext, numtts
        
    time.sleep(1.0)  
    
    while not stop_event.is_set():  # Keep running until stop_event is set
  
        if not text_queue.empty():

            text = text_queue.get(timeout = 1)  # Wait for 1 second for an item
             
            if len(text) > 0:
                # print(text)
                try:
                    mp3file1 = BytesIO()
                    tts = gTTS(text, lang = "en", tld = 'us') 
                    tts.write_to_fp(mp3file1)
                except Exception as e:
                    continue
                
                audio_queue.put(mp3file1)
                numtts += 1  
                text_queue.task_done()
                
        #print("\n numtts, numtext : ", numtts , numtext)
        
        if llm_done.is_set() and numtts == numtext: 
            
            time.sleep(0.3) 
            tts_done.set()
            mp3file1 = None
            #print("\n break from the text queue" )

            break
            

# thread 3 for audio playback 
def play_audio(audio_queue,tts_done, stop_event):
 
    global numtts, numaudio, rled 
        
    #print("start play_audio()")
    while not stop_event.is_set():  # Keep running until stop_event is set

        mp3audio1 = BytesIO() 
        mp3audio1 = audio_queue.get()  

        mp3audio1.seek(0)  
         
        rled.on()
        
        mixer.music.load(mp3audio1, "mp3")
        mixer.music.play()

        #print("Numaudio: ", numaudio )  

        while mixer.music.get_busy():
            time.sleep(0.2) 
        
        numaudio += 1 
        audio_queue.task_done()
        
        #print("\n numtts, numaudio : ", numtts , numaudio)
            
        rled.off()
 
        if tts_done.is_set() and numtts  == numaudio: 
            mp3audio1 = None
            #print("\n no more audio/text data, breaking from audio thread")
            break  # Exit loop      
 
# save conversation to a log file 
def append2log(text):
    global today
    fname = 'chatlog-' + today + '.txt'
    with open(fname, "a", encoding='utf-8') as f:
        f.write(text + "\n")
        f.close 
      
# define default language to work with the AI model 
slang = "en-EN"

# Load devices from devices.json
devices = []
with open('devices.json', 'r') as f:
    devices = json.load(f)

# Main function  
def main():
    global today, slang, numtext, numtts, numaudio, messages, rled, gled
    
    rec = sr.Recognizer()
    mic = sr.Microphone()
    
    rec.energy_threshold = 4000    
  
    sleeping = True 
    # while loop for conversation 
    while True:     
    
        with mic as source:            
            rec.adjust_for_ambient_noise(source, duration= 1)
            rec.dynamic_energy_threshold= True
            
            try: 
                gled.on()
                print("Listening ...")                
                audio = rec.listen(source, timeout = 10 ) #, phrase_time_limit = 30) 
                text =  rec.recognize_google(audio, language=slang)   # rec.recognize_wit(audio, key=wit_api_key ) #
                # print(text)
                
                if len(text)>0:
                    print(f"You: {text}\n " )
                else:
                    print(f"Unable to recognize your speech. Program will exit. \n " )
                    break
                
                gled.off()                 
                # AI is in sleeping mode
                if sleeping == True:
                    # User can start the conversation with the wake word "Jack"
                    # This word can be changed below. 
                    if "jack" in text.lower() and slang == "en-EN":
                        request = text.lower().split("jack")[1]
                        
                        sleeping = False
                        # AI is awake now, 
                        # start a new conversation 

                        chat = model.start_chat(history=[])

                        append2log(f"_"*40)                    
                        today = str(date.today())  
                        
                        messages = []                      
                     
                        # if the user's question is none or too short, skip 
                        if len(request) < 2:

                            speak_text("Hi, there, how can I help?")
                            append2log(f"AI: Hi, there, how can I help? \n")
                            continue                      
     
                    # if user did not say the wake word, nothing will happen 
                    else:
                        print(f"Please start the conversation with the wake word. \n " )
                        continue
                      
                # AI is awake         
                else: 
                    
                    request = text.lower()

                    if "that's all" in request:
                                               
                        append2log(f"You: {request}\n")
                        
                        speak_text("Bye now")
                        
                        append2log(f"AI: Bye now. \n")                        

                        sleeping = True
                        # AI goes back to sleeping mode
                        continue
                    
                    if "jack" in request:
                        request = request.split("jack")[1]
                    
                    # Handle smart home commands
                    if 'turn on' in request or 'turn off' in request:
                        action = 'on' if 'turn on' in request else 'off'
                        device_found = False
                        for device in devices:
                            if device['name'].lower() in request:
                                device_found = True
                                device_ip = device['ip']
                                control_url = f"http://{device_ip}/{action}"
                                try:
                                    response = requests.get(control_url)
                                    if response.status_code == 200:
                                        speak_text(f"OK, turning {action} {device['name']}")
                                        append2log(f"AI: OK, turning {action} {device['name']}\n")
                                    else:
                                        speak_text(f"Sorry, I couldn't turn {action} {device['name']}")
                                        append2log(f"AI: Sorry, I couldn't turn {action} {device['name']}\n")
                                except Exception as e:
                                    speak_text(f"Sorry, there was an error controlling {device['name']}")
                                    append2log(f"AI: Error controlling {device['name']}: {e}\n")
                                break
                        if not device_found:
                            speak_text("Sorry, I didn't recognize the device")
                            append2log("AI: Device not recognized\n")
                        continue

                    elif 'how many lights are on' in request:
                        # Query the state API
                        try:
                            response = requests.get('http://172.20.10.4/state')
                            if response.status_code == 200:
                                state = response.json()
                                num_lights_on = sum(1 for v in state.values() if v)
                                speak_text(f"There are {num_lights_on} lights on")
                                append2log(f"AI: There are {num_lights_on} lights on\n")
                            else:
                                speak_text("Sorry, I couldn't get the state of the lights")
                                append2log("AI: Could not get the state of the lights\n")
                        except Exception as e:
                            speak_text("Sorry, there was an error getting the state of the lights")
                            append2log(f"AI: Error getting state of lights: {e}\n")
                        continue

                    # process user's request (question)
                    append2log(f"You: {request}\n ")

                    print(f"AI: ", end='')
                    
                    # Initialize the counters before each reply from AI 
                    numtext = 0 
                    numtts = 0 
                    numaudio = 0
                    
                    # Define text and audio queues for data storage 
                    text_queue = queue.Queue()
                    audio_queue = queue.Queue()
                    
                    # Define events
                    llm_done = threading.Event()                
                    tts_done = threading.Event() 
                    stop_event = threading.Event()                
     
                    # Thread 1 for handling the LLM responses 
                    llm_thread = threading.Thread(target=chatfun, args=(request, text_queue,llm_done,stop_event,))

                    # Thread 2 for text-to-speech 
                    tts_thread = threading.Thread(target=text2speech, args=(text_queue,tts_done,llm_done, audio_queue, stop_event,))
                    
                    # Thread 3 for audio playback 
                    play_thread = threading.Thread(target=play_audio, args=(audio_queue,tts_done, stop_event,))

                    llm_thread.start()
                    tts_thread.start()
                    play_thread.start()
                    
                    # wait for LLM to finish responding
                    llm_done.wait()

                    llm_thread.join() 
                    
                    tts_done.wait()
                    
                    audio_queue.join()
     
                    stop_event.set()  
                    tts_thread.join()
     
                    play_thread.join()  
     
                    print('\n')
 
            except Exception as e:
                continue 

if __name__ == "__main__":
    main()
