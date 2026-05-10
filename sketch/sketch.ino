#include <Bridge.h>

// Pins Semàfor Zona 1
const int Z1_V = 2; // Vermell
const int Z1_G = 3; // Groc
const int Z1_D = 4; // Verd

// Pins Semàfor Zona 2
const int Z2_V = 5;
const int Z2_G = 6;
const int Z2_D = 7;

void setup() {
  // Inicialitzem el Bridge (imprescindible per comunicar amb el Python del App Lab)
  Bridge.begin();

  // Configurem pins com a sortida
  pinMode(Z1_V, OUTPUT); pinMode(Z1_G, OUTPUT); pinMode(Z1_D, OUTPUT);
  pinMode(Z2_V, OUTPUT); pinMode(Z2_G, OUTPUT); pinMode(Z2_D, OUTPUT);
  
  // Per defecte, tots en vermell per seguretat al arrencar
  digitalWrite(Z1_V, HIGH);
  digitalWrite(Z2_V, HIGH);
}

void loop() {
  // Buffers per guardar el text ("VERD" o "VERMELL")
  char buffer1[15];
  char buffer2[15];

  // L'Arduino mira què hi ha escrit a les claus que el Python ha omplert
  Bridge.get("semafor_1", buffer1, 15);
  Bridge.get("semafor_2", buffer2, 15);

  // Actualitzem els LEDs físics segons el contingut dels buffers
  processarSemafor(Z1_V, Z1_G, Z1_D, String(buffer1));
  processarSemafor(Z2_V, Z2_G, Z2_D, String(buffer2));

  delay(100); // Freqüència de refresc (10 vegades per segon)
}

void processarSemafor(int pV, int pG, int pD, String estat) {
  if (estat == "VERD") {
    digitalWrite(pV, LOW);
    digitalWrite(pG, LOW);
    digitalWrite(pD, HIGH);
  } 
  else if (estat == "VERMELL") {
    // Si estava en verd i anem a vermell, fem una transició de groc
    if (digitalRead(pD) == HIGH) {
      digitalWrite(pD, LOW);
      digitalWrite(pG, HIGH);
      delay(2000); // 2 segons de precaució
      digitalWrite(pG, LOW);
    }
    digitalWrite(pV, HIGH);
    digitalWrite(pG, LOW);
    digitalWrite(pD, LOW);
  }
}
