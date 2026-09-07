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

## Tests

```bash
npm test
```

## GitHub Pages

El repositorio incluye `.github/workflows/pages.yml` para probar la lógica y publicar automáticamente la web al hacer push a `main`.

En GitHub: **Settings → Pages → Source → GitHub Actions**.

La geolocalización y el service worker requieren HTTPS; GitHub Pages lo proporciona.

## Actualizar festivos

Editar `HOLIDAYS` y `HOLIDAY_YEARS` en `data.js`.
