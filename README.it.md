# Curve Digitizer

Applicazione desktop Python 3 + Tkinter per digitalizzare manualmente curve da grafici di vecchi datasheet.

## Funzioni

- PNG/JPG/TIFF
- zoom con rotella, pan, fit alla finestra
- coordinate pixel sotto il cursore
- calibrazione a quattro punti con omografia
- assi X/Y lineari o logaritmici
- più serie con parametro, valore e unità
- aggiunta, eliminazione e spostamento punti
- undo/redo
- serie visibili/nascoste
- numerazione progressiva opzionale
- snap opzionale verso il pixel più scuro, con click manuale conservato separatamente
- progetto JSON UTF-8
- riapertura completa progetto
- export CSV configurabile
- Verify calibration con residui rispetto ai valori attesi

L'immagine originale non viene mai sovrascritta o modificata.

## Requisiti

Python 3, Tkinter/Tcl-Tk, Pillow e NumPy.

Su Debian/Ubuntu, se Tkinter manca:

```bash
sudo apt install python3-tk
```

Installazione Python opzionale:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Avvio

```bash
python3 curve_digitizer.py
```

Compatibile con X11 forwarding, ad esempio:

```bash
ssh -X host
python3 curve_digitizer.py
```

## Primo test: 6BX7-GT

Configurare:

```text
X name: Plate Voltage
X unit: V
X min: 0
X max: 500
X scale: linear

Y name: Plate Current
Y unit: mA
Y min: 0
Y max: 70
Y scale: linear
```

Premere `Apply axis settings`, poi acquisire nell'ordine:

1. bottom-left
2. bottom-right
3. top-left
4. top-right

Usare `Verify calibration` su una intersezione nota della griglia.

Creare quindi una serie:

```text
Series name: Vg_-20V
Parameter name: Vg
Parameter value: -20
Parameter unit: V
```

Inserire i punti in modalità `Add points`; per correggerli usare `Edit / move points`.

Per l'export CSV:

```text
X name: Va
X unit: V
Y name: Ia
Y unit: mA
Series parameter name: Vg
Series parameter unit: V
```

Esempio di output:

```csv
Va_V,Vg_V,Ia_mA
100,-20,12.3
120,-20,18.1
```

## Scorciatoie

```text
Ctrl+O          Open image
Ctrl+Shift+O    Open project
Ctrl+S          Save project
Ctrl+Shift+S    Save project as
Ctrl+E          Export CSV
Ctrl+Z          Undo
Ctrl+Y          Redo
Delete          Delete selected point
F               Fit image to window
Wheel           Zoom
Middle drag     Pan
Right drag      Pan
```

## Licenza

GNU GPL v3 o successiva.
