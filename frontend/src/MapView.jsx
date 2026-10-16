import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api, getKey, url } from './api'
import Card from './Card'

const BASE_STYLE = {
  version: 8,
  sources: {
    osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 19,
      attribution: '© OpenStreetMap contributors' },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#DDE3DC' } },
    { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-saturation': -0.6, 'raster-opacity': 0.85 } },
  ],
}

export default function MapView({ meta, lang, onPlan }) {
  const el = useRef(null)
  const map = useRef(null)
  const [overlays, setOverlays] = useState(null)
  const [targets, setTargets] = useState([])
  const [occ, setOcc] = useState([])
  const [show, setShow] = useState('rank')
  const [layers, setLayers] = useState({ unc: true, tgt: true, occ: true })
  const [sel, setSel] = useState(null) // {target} | {lon,lat}
  const [ready, setReady] = useState(false)
  const geo = meta.role === 'geologist'

  useEffect(() => {
    api.get('/api/overlays').then(setOverlays)
    api.get('/api/targets').then((t) => { setTargets(t); if (t[0]) setSel({ target: t[0].id }) })
    if (geo) api.get('/api/occurrences').then(setOcc).catch(() => setOcc([]))
  }, [meta.version, meta.role, geo])

  useEffect(() => {
    const [w, s, e, n] = meta.bbox
    const m = new maplibregl.Map({ container: el.current, style: BASE_STYLE, bounds: [[w, s], [e, n]],
      fitBoundsOptions: { padding: 20 }, attributionControl: { compact: true },
      // overlays behind the geologist key need the Authorization header too
      transformRequest: (url) => (url.includes('/api/') && getKey() ? { url, headers: { Authorization: `Bearer ${getKey()}` } } : { url }) })
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    // 'load' waits for basemap tiles, which never arrive offline; the style is enough to draw our layers
    m.once('style.load', () => setReady(true))
    m.on('click', (ev) => {
      const f = m.queryRenderedFeatures(ev.point, { layers: ['tgt-circle', 'tgt-block'].filter((id) => m.getLayer(id)) })
      if (f.length) setSel({ target: f[0].properties.id })
      else setSel({ lon: ev.lngLat.lng, lat: ev.lngLat.lat })
    })
    map.current = m
    return () => m.remove()
  }, [meta.bbox, meta.role])

  // raster overlays
  useEffect(() => {
    const m = map.current
    if (!ready || !overlays) return
    const setImage = (id, ov, opacity, before, resampling = 'linear') => {
      if (m.getLayer(id)) m.removeLayer(id)
      if (m.getSource(id)) m.removeSource(id)
      if (!ov) return
      m.addSource(id, { type: 'image', url: url(ov.url) + `?v=${meta.version}`, coordinates: ov.coords })
      m.addLayer({ id, type: 'raster', source: id, paint: { 'raster-opacity': opacity, 'raster-resampling': resampling, 'raster-fade-duration': 0 } },
        before && m.getLayer(before) ? before : undefined)
    }
    const main = show === 'rank' ? overlays.rank : overlays.evidence?.[show]
    setImage('main', main, 0.9, 'tgt-block')
    setImage('unc', layers.unc ? overlays.uncertainty : null, 0.9, 'tgt-block', 'nearest')
  }, [ready, overlays, show, layers.unc, meta.version])

  // vector layers
  useEffect(() => {
    const m = map.current
    if (!ready) return
    const fc = {
      type: 'FeatureCollection',
      features: targets.map((t) => ({ type: 'Feature', properties: { id: t.id, rank: String(t.rank), sel: sel?.target === t.id },
        geometry: { type: 'Point', coordinates: [t.lon, t.lat] } })),
    }
    const blocks = {
      type: 'FeatureCollection',
      features: targets.filter((t) => t.block).map((t) => ({ type: 'Feature', properties: { id: t.id, sel: sel?.target === t.id },
        geometry: { type: 'Polygon', coordinates: [t.block] } })),
    }
    const occFc = { type: 'FeatureCollection', features: occ.map((o) => ({ type: 'Feature', properties: { set: o.set },
      geometry: { type: 'Point', coordinates: [o.lon, o.lat] } })) }
    const upsert = (id, data) => (m.getSource(id) ? m.getSource(id).setData(data) : m.addSource(id, { type: 'geojson', data }))
    upsert('targets', fc); upsert('blocks', blocks); upsert('occ', occFc)
    if (!m.getLayer('tgt-block')) {
      m.addLayer({ id: 'tgt-block', type: 'fill', source: 'blocks', paint: { 'fill-color': '#000', 'fill-opacity': 0.01 } })
      m.addLayer({ id: 'tgt-block-line', type: 'line', source: 'blocks', paint: {
        'line-color': ['case', ['get', 'sel'], '#B4532A', '#141B19'], 'line-width': ['case', ['get', 'sel'], 3, 1.5] } })
      m.addLayer({ id: 'occ', type: 'circle', source: 'occ', paint: {
        'circle-radius': 4.5, 'circle-color': ['case', ['==', ['get', 'set'], 'train'], '#141B19', '#ffffff'],
        'circle-stroke-color': ['case', ['==', ['get', 'set'], 'train'], '#ffffff', '#141B19'], 'circle-stroke-width': 1.6 } })
      m.addLayer({ id: 'tgt-circle', type: 'circle', source: 'targets', paint: {
        'circle-radius': ['case', ['get', 'sel'], 13, 10], 'circle-color': ['case', ['get', 'sel'], '#B4532A', '#141B19'],
        'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } })
    }
    m.setLayoutProperty('occ', 'visibility', layers.occ ? 'visible' : 'none')
    for (const id of ['tgt-block', 'tgt-block-line', 'tgt-circle']) m.setLayoutProperty(id, 'visibility', layers.tgt ? 'visible' : 'none')
    // rank numbers drawn as HTML markers (no glyph server needed offline)
    m._wanaMarkers?.forEach((mk) => mk.remove())
    m._wanaMarkers = layers.tgt ? targets.map((t) => {
      const d = document.createElement('div')
      d.className = 'tgt-num'
      d.textContent = t.rank
      d.onclick = (e) => { e.stopPropagation(); setSel({ target: t.id }) }
      return new maplibregl.Marker({ element: d }).setLngLat([t.lon, t.lat]).addTo(m)
    }) : []
  }, [ready, targets, occ, sel, layers.tgt, layers.occ])

  const evOptions = overlays?.evidence ? Object.entries(overlays.evidence) : []
  return (
    <div className="bench">
      <aside className="rail">
        <div className="panel">
          <label className="label" htmlFor="show">Show on map</label>
          <select id="show" className="full" value={show} onChange={(e) => setShow(e.target.value)}>
            <option value="rank">Chrome ranking (model v{meta.version})</option>
            {evOptions.map(([k, v]) => <option key={k} value={k}>Evidence: {v.label}</option>)}
          </select>
          <div className="layers">
            <Toggle id="unc" label="Low-confidence hatching" note="Ensemble disagreement and missing layers." v={layers.unc} set={setLayers} />
            <Toggle id="tgt" label="Ranked targets" note={geo ? 'Exact points (geologist view).' : 'Shown as 1 km blocks.'} v={layers.tgt} set={setLayers} />
            {geo && <Toggle id="occ" label="Known occurrences" note="Black = training, white = held-out test." v={layers.occ} set={setLayers} />}
          </div>
          {!geo && <p className="muted small">Miner view: exact points and the full-resolution ranking are only served to registered users.</p>}
        </div>
        <div className="panel">
          <div className="label">Ranked targets</div>
          <div className="tlist">
            {targets.map((t) => (
              <button key={t.id} className="trow" aria-current={sel?.target === t.id} onClick={() => {
                setSel({ target: t.id }); map.current?.flyTo({ center: [t.lon, t.lat], zoom: Math.max(map.current.getZoom(), 13) })
              }}>
                <span className="rk">{String(t.rank).padStart(2, '0')}</span>
                <span><span className="nm">{t.id}</span><br /><span className={`pill ${t.confidence}`}>{t.confidence}</span></span>
                <span className="sc">{Math.round(t.score)}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>
      <div className="mapcol">
        <div className="mapframe" ref={el} />
        <div className="legend">
          {show === 'rank'
            ? <span><span className="ramp" /> Best 30% of ground{geo ? '' : ' (1 km blocks)'}</span>
            : <span><span className="ramp ev" /> {overlays?.evidence?.[show]?.label}: low → high, grey = no data</span>}
          <span><span className="sw hatch" /> Low confidence</span>
        </div>
      </div>
      <div className="cardcol">
        {sel && <Card sel={sel} lang={lang} role={meta.role} version={meta.version} onPlan={onPlan} />}
      </div>
    </div>
  )
}

function Toggle({ id, label, note, v, set }) {
  return (
    <div className="layer">
      <input type="checkbox" id={`L-${id}`} checked={v} onChange={(e) => set((s) => ({ ...s, [id]: e.target.checked }))} />
      <label htmlFor={`L-${id}`}>{label}</label>
      <small>{note}</small>
    </div>
  )
}
