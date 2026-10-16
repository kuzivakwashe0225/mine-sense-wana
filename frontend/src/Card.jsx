import { useQuery } from './query'
import { T } from './i18n'

export default function Card({ sel, lang, role, version, onPlan }) {
  const t = T[lang]
  const params = sel.target ? { target: sel.target, lang, v: version, r: role } : { lon: sel.lon, lat: sel.lat, lang, v: version, r: role }
  const q = useQuery('/api/card', params)
  const c = q.data
  if (q.error && !c) return <div className="panel muted">{q.error.message}</div>
  if (!c) return <div className="panel muted">Loading…</div>
  const mx = Math.max(0.01, ...c.why.map((w) => Math.abs(w.value)), ...c.against.map((w) => Math.abs(w.value)))
  const loc = c.location
  return (
    <article className="card" data-reading>
      <header className="card-head">
        <div className="id">{c.target ? t.rank(c.target.rank, c.target.of) : t.cell}</div>
        <h2>{c.target ? c.target.id : `${Math.abs(loc.lat).toFixed(3)}°S ${loc.lon.toFixed(3)}°E`}</h2>
        <div className="scoreline">
          <div>
            <div className="label inv">{t.chance}</div>
            <div className="big">{Math.round(c.score)}<small> /100</small></div>
            <div className="small inv">{t.topPct(c.percentile_top)}</div>
          </div>
          <div>
            <div className="label inv">{t.conf}</div>
            <span className={`pill ${c.confidence}`}>{c.confidence_label}</span>
          </div>
        </div>
      </header>
      <div className="card-body">
        <section>
          <h3>{t.location}</h3>
          <div className="mono">{Math.abs(loc.lat).toFixed(role === 'geologist' ? 5 : 3)}°S, {loc.lon.toFixed(role === 'geologist' ? 5 : 3)}°E
            <span className="muted"> · ±{loc.precision_m >= 1000 ? `${loc.precision_m / 1000} km` : `${loc.precision_m} m`}</span></div>
          {c.location_note && <p className="small muted">{c.location_note}</p>}
          {c.site && <p className="small muted">Slope {c.site.slope_deg}°</p>}
        </section>
        <section>
          <h3>{t.why}</h3>
          <ul className="why">{c.why.map((w) => <li key={w.feature}><Bar v={w.value / mx} /><span>{w.text}</span></li>)}</ul>
        </section>
        {(c.against.length > 0 || c.missing.length > 0) && (
          <section>
            <h3>{t.against}</h3>
            <ul className="why">
              {c.against.map((w) => <li key={w.feature}><Bar v={-w.value / mx} neg /><span>{w.text}</span></li>)}
              {c.missing.map((m) => <li key={m}><Bar v={0.4} neg /><span>{m}</span></li>)}
            </ul>
          </section>
        )}
        <section>
          <h3>{t.check}</h3>
          <ol className="checks">{c.check_first.map((x) => <li key={x}>{x}</li>)}</ol>
        </section>
        <section>
          <h3>{t.safety}</h3>
          {c.safety.map((s) => <div key={s} className={`flag ${c.safety_flagged ? '' : 'info'}`}>{s}</div>)}
        </section>
        <section>
          <h3>{t.rights}</h3>
          <div className="access">{c.rights}</div>
        </section>
        {c.target && <button className="btn primary" onClick={() => onPlan(c.target.id)}>{t.plan}</button>}
        <p className="disclaim">{c.disclaimer}</p>
      </div>
    </article>
  )
}

function Bar({ v, neg }) {
  return <div className="bar"><i className={neg ? 'neg' : ''} style={{ width: `${Math.round(Math.min(1, Math.abs(v)) * 100)}%` }} /></div>
}
