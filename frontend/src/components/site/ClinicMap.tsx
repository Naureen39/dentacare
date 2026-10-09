import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { MapContainer, Marker, TileLayer } from 'react-leaflet'

import { clinic } from '@/content/site'

// Leaflet looks for its marker pictures next to its own stylesheet, which a bundler does not
// copy. A small inline marker avoids the extra files and the broken image that goes with them.
const marker = L.divIcon({
  className: '',
  html: '<div style="width:28px;height:28px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:#0b7371;border:3px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3)"></div>',
  iconSize: [28, 28],
  iconAnchor: [14, 28],
})

/** An OpenStreetMap map with one marker. Loaded only when its section nears the screen. */
export default function ClinicMap() {
  return (
    <MapContainer
      center={[clinic.geo.lat, clinic.geo.lng]}
      zoom={15}
      scrollWheelZoom={false}
      className="h-80 w-full rounded-xl md:h-full md:min-h-96"
      aria-label={`Map showing ${clinic.name}`}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Marker
        position={[clinic.geo.lat, clinic.geo.lng]}
        icon={marker}
        interactive={false}
        keyboard={false}
      />
    </MapContainer>
  )
}
