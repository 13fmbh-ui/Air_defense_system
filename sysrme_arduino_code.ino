#include <Servo.h>

Servo servoX;
Servo servoY;
Servo servoFire; 

const int servoXPin = 9;    
const int servoYPin = 10;   
const int servoFirePin = 11; 
int lastAngleX = 90;
int lastAngleY = 45;
int lastAngleFire = 50; 


void setup() {
  Serial.begin(9600);
  
  servoX.attach(servoXPin);
  servoY.attach(servoYPin);
  servoFire.attach(servoFirePin);
  
  servoX.write(lastAngleX);
  servoY.write(lastAngleY);
  servoFire.write(lastAngleFire);
}

void loop() {
  if (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    
    int comma1 = data.indexOf(',');
    int comma2 = data.indexOf(',', comma1 + 1);
    
    if (comma1 != -1 && comma2 != -1) {
      int targetX = data.substring(0, comma1).toInt();
      int targetY = data.substring(comma1 + 1, comma2).toInt();
      int fireSignal = data.substring(comma2 + 1).toInt();
      
      targetX = constrain(targetX, 0, 180);
      targetY = constrain(targetY, 45, 180);
      
      if (targetX != lastAngleX) {
        servoX.write(targetX);
        lastAngleX = targetX;
      }
      
      
      if (targetY != lastAngleY) {
        servoY.write(targetY);
        lastAngleY = targetY;
      }
      
      int targetFireAngle = 50; 
      
      if (fireSignal == 1) {
        targetFireAngle = 0;  
      } else {
        targetFireAngle = 50; 
      }
      
      if (targetFireAngle != lastAngleFire) {
        servoFire.write(targetFireAngle);
        lastAngleFire = targetFireAngle;
      }
    }
  }
}