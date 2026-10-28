
int laserPin1 = 2; 
int laserPin2 = 3; 
int camPin = 4;
int statusPin = 13;

String inputString = "";         // a string to hold incoming data
boolean stringComplete = false;  // whether the string is complete
char  bufferString[10];

unsigned long previousMillis = 0;
unsigned long interval = 1000; 
bool trigger = false;

char ibyte;
void setup()
{
  pinMode(laserPin1, OUTPUT); 
  pinMode(laserPin2, OUTPUT); 
  pinMode(camPin, OUTPUT);
  pinMode(statusPin, OUTPUT);
  digitalWrite(laserPin1, LOW);
  digitalWrite(laserPin2, LOW);
  digitalWrite(camPin, LOW);
  digitalWrite(statusPin, HIGH);
  // initialize serial:
  Serial.begin(9600);
  // reserve 200 bytes for the inputString:
  inputString.reserve(200);
  
}

// 1 => laserPin1 -> HIGH
// 2 => laserPin1 -> LOW
// 3 => laserPin2 -> HIGH
// 4 => laserPin2 -> LOW

void loop()
{
  serialEvent();
  if(stringComplete)
  {
    if(inputString.charAt(0) == '?')
      Serial.println("trigger\n");
    if(inputString.charAt(0) == 'A')
    {
      if(inputString.charAt(1) == '1')
      {
        digitalWrite(laserPin1, HIGH);
        Serial.println("1 on");
      }
      else
      {
        digitalWrite(laserPin1, LOW);
        Serial.println("1 off");
      }
    }
    else if(inputString.charAt(0) == 'B')
    {
      if(inputString.charAt(1) == '1')
      {
        digitalWrite(laserPin2, HIGH);
        Serial.println("2 on");
      }
      else
      {
        digitalWrite(laserPin2, LOW);
        Serial.println("2 off");
      }
    }
    else if(inputString.charAt(0) == 'C')
    {
      if(inputString.charAt(1) == '+')
      {
        digitalWrite(camPin, HIGH);
        digitalWrite(13, HIGH);
        delay(10); 
        digitalWrite(camPin, LOW);
        digitalWrite(13, LOW);
        trigger = false;
        Serial.println("done");
      }
      else if(inputString.charAt(1) == '-')
      {
        trigger = false;
      }
      else
      {
        digitalWrite(camPin, LOW);
        inputString.substring(1).toCharArray(bufferString,10);
        interval = atof(bufferString);
        previousMillis = millis();
        trigger = true;
      }
    }
    inputString = "";
    stringComplete = false;
  }
  if(trigger)
  if (millis() - previousMillis > interval) {
      digitalWrite(camPin, HIGH);
      digitalWrite(13, HIGH);
      delay(10); 
      digitalWrite(camPin, LOW);
      digitalWrite(13, LOW);
      previousMillis = previousMillis+interval;//millis();
  }
}

/*
  SerialEvent occurs whenever a new data comes in the
 hardware serial RX.  This routine is run between each
 time loop() runs, so using delay inside loop can delay
 response.  Multiple bytes of data may be available.
 */
void serialEvent() {
  while (Serial.available()) {
    // get the new byte:
    char inChar = (char)Serial.read();
    // add it to the inputString:
    inputString += inChar;
    // if the incoming character is a newline, set a flag
    // so the main loop can do something about it:
    if (inChar == '\n') {
      stringComplete = true;
    }
  }
}
