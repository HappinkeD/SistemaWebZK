# Sistema de Gestión Biométrica - HRCV

Software para la sincronización de huellas y descarga de reportes detallados.

## Configuración
- **Puerto:** 8090
- **Base de Datos:** PostgreSQL en 192.168.42.244:5442
- **Equipos:** - G1 Piso 1 (192.168.43.199)
  - G1 Piso 2 (192.168.43.198)

## Despliegue
Para generar el ejecutable:
`python -m PyInstaller --noconfirm --onedir --windowed --add-data "templates;templates" --name "Biometrico_HRCV" app.py`