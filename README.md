# Sem Sense

# Sem Sense

## =========== ENG ============

### Inspiration
Have you ever pressed a crosswalk button and, after waiting with no response, decided to cross on red? Only to find that once you’re across, the light turns green and cars are forced to stop and idle for no reason?

### What it does
We’ve connected two cameras to an intersection that detect pedestrian intent (are they waiting to cross, or just walking by?). Using this data, the system automatically "presses the button" intelligently.

However, this isn't just a simple "stop everything" command. Our system also monitors approaching traffic to decide the optimal time to change the lights. Our goals are:
* **Reducing emissions**: by avoiding unnecessary stops and improving traffic flow.
* **Ensuring safety**: by preventing pedestrians from feeling the need to cross on red.
* **Increasing resilience**: through a central node that allows for manual monitoring and calibration.

### How we built it
First, we created a physical scale model simulating a T-junction with toy cars and rubber ducks (representing pedestrians).

Using the model, we generated a categorized image dataset to train an **Edge AI** model capable of detecting cars, pedestrians, and their specific intentions.

This model was deployed on two boards that communicate with a central node, which is responsible for:
* Aggregating data and deciding the best traffic light sequence using a custom algorithm.
* Sending commands to the peripheral nodes to execute the master node's instructions.

Additionally, we developed a monitoring environment (within the master node) to visualize the real-time status of the entire intersection.

### How to replicate this project
To replicate this project at home, follow the steps outlined in our build process:
1. **Design your model**: use cardboard, paint, tape, or other craft materials.
2. **Data collection**: take a large number of images showing different intersection states and categorize them in *Edge Impulse*.
3. **Train the model**: use the images with the following output categories:
    * `ducks_waiting_to_cross`
    * `cars_before_intersection`
4. **Deploy the code**: copy the software from this repository and apply it to the corresponding boards.

### What's next for Sem Sense
This is currently a proof of concept. Future iterations could include:
* Specific detection of bicycles, ambulances, and pedestrians with mobility issues for prioritized management.
* Multi-intersection synchronization to manage traffic flow across an entire grid.
* Scaling the logic for complex, high-traffic intersections.

---

## =========== CAT ============

### Inspiració
Heu pitjat mai el botó d'un semàfor i, com que no passava res, heu acabat creuant en vermell? I just quan sou a l'altra banda, es posa verd i els cotxes s'aturen inútilment, contaminant sense motiu?

### Què fa
Hem connectat dues càmeres a una intersecció que detecten la intenció dels vianants (volen creuar o només passen de lluny?). Amb aquesta informació, el sistema decideix "prémer el botó" de manera intel·ligent.

Ara bé, no és un botó convencional de "paro, m'espero i torno a l'inici". El nostre sistema també monitoritza el trànsit que s'apropa i és capaç de decidir si cal esperar que passin els cotxes o no, amb l'objectiu de:
* **Reduir emissions**: evitant esperes innecessàries i millorant la fluïdesa del trànsit.
* **Garantir un pas segur**: evitant que els vianants s'impacientin i creuin en vermell.
* **Augmentar la resiliència**: mitjançant un sistema de monitoratge i calibratge manual en un node central.

### Com ho hem construït
Primer de tot, hem creat una maqueta física que simula una intersecció en T amb cotxes de joguina i aneguets de plàstic (vianants).

A partir de la maqueta, hem generat un *dataset* d'imatges categoritzades per tal d'entrenar un model d'**Edge IA** capaç de detectar tant els cotxes com els vianants, així com les seves intencions.

Aquest model l'hem implementat en dues plaques que es comuniquen amb un node central, el qual s'encarrega de:
* Agrupar les dades i decidir la millor combinació de semàfors mitjançant un algorisme.
* Enviar ordres als nodes perifèrics perquè executin les instruccions del node mestre.

Addicionalment, hem creat un entorn de monitoratge (dins del node mestre) des d'on es pot visualitzar l'estat complet de la intersecció en temps real.

### Com replicar el projecte
Per tal de replicar aquest projecte a casa vostra, cal seguir els passos especificats a l'etapa de construcció. En resum:
1. **Dissenyar la maqueta**: utilitzant cartró, pintura, cinta adhesiva o el que tingueu a mà.
2. **Capturar dades**: prendre un gran nombre d'imatges dels diferents estats de la intersecció i categoritzar-les a *Edge Impulse*.
3. **Entrenar el model**: utilitzar les imatges amb les següents categories de sortida:
    * `aneguets_esperant_creuar`
    * `cotxes_abans_intersecció`
4. **Implementar el codi**: copiar el programari d'aquest repositori i carregar-lo a les plaques corresponents.

### El futur de Sem Sense
Això és només una prova de concepte. Iteracions futures del projecte podrien incloure:
* Detecció específica de bicicletes, ambulàncies o persones amb mobilitat reduïda per a una gestió prioritària.
* Sincronització de múltiples cruïlles simultàniament, tenint en compte el flux de trànsit global.
* Escalat del sistema per a interseccions de grans dimensions.
