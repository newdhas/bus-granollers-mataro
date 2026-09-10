# Bus Granollers ↔ Mataró

PWA estática para consultar los 5 próximos autobuses e13 entre:

- **Granollers → Mataró**: salida desde *Estació d’Autobusos de Granollers*.
- **Mataró → Granollers**: salida desde *Sant Crist · Camí del Mig*.

## Funciones

- Geolocalización para escoger automáticamente el sentido.
- Selector manual de trayecto.
- Próximas 5 salidas y cuenta atrás en minutos.
- Hora prevista de llegada.
- Calendario laborable / fin de semana-festivo de verano / invierno.
- Festivos 2026 de Cataluña y festivos locales de Granollers y Mataró.
- Expediciones `saturdayOnly` únicamente en sábados no festivos.
- Cruce de medianoche.
- PWA con service worker y funcionamiento offline tras la primera carga.
- Enlace al horario oficial de Sagalés.
- Monitor automático del PDF oficial de horarios.

## Monitor automático del horario

El workflow `.github/workflows/monitor-timetable.yml` comprueba el horario oficial de Sagalés aproximadamente cada 6 horas.

El monitor usa el mismo endpoint que utiliza el botón **Horarios (pdf)** de la página oficial de la línea e13. Guarda el SHA-256 del PDF aceptado y una huella normalizada de los horarios.

Cuando encuentra un PDF distinto:

1. Descarga el PDF oficial.
2. Extrae las dos direcciones y los tres calendarios (laborables, junio-septiembre y octubre-mayo).
3. Valida la estructura de paradas, el orden de las expediciones, las duraciones y las filas exclusivas de sábado.
4. Si el horario realmente ha cambiado, genera de nuevo `TIMETABLES` en `data.js`.
5. Ejecuta los tests de la aplicación.
6. Solo si todo es correcto hace commit automático; ese commit vuelve a desplegar GitHub Pages.

Si el PDF cambia de formato, no se puede extraer con seguridad o los tests fallan, **no se publica ningún horario nuevo**. En ese caso el workflow crea un Issue llamado `Nuevo PDF e13 pendiente de validar` para revisión manual.

El estado del último PDF aceptado se guarda en `monitor/e13-state.json`.

## Tests

```bash
npm test
```

## GitHub Pages

El repositorio incluye `.github/workflows/pages.yml` para probar la lógica y publicar automáticamente la web al hacer push a `main`.

En GitHub: **Settings → Pages → Source → GitHub Actions**.

La geolocalización y el service worker requieren HTTPS; GitHub Pages lo proporciona.

El service worker usa estrategia *network-first*: cuando el monitor actualiza `data.js`, la PWA instalada recibe el horario nuevo al volver a tener conexión y conserva la última versión válida para uso offline.

## Actualizar festivos

Editar `HOLIDAYS` y `HOLIDAY_YEARS` en `data.js`.
