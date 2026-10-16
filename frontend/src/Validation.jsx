import { useEffect, useState } from 'react'
import { api } from './api'

export default function Validation({ version }) {
  const [v, setV] = useState(null)
  useEffect(() => { api.get('/api/validation').then(setV) }, [version])
  if (!v) return <p className="muted">Loading…</p>
  const m = v.metrics
  if (!m.curve) return <p className="muted">No held-out occurrences in this pilot area yet, so the model cannot be tested. Add occurrences south of the hold-out line.</p>
  const W = 640, H = 380, L = 56, R = 16, Tp = 16, B = 48, pw = W - L - R, ph = H - Tp - B
  const px = (a) => L + a * pw, py = (c) => Tp + ph - c * ph
  const path = m.curve.map(([a, c], i) => `${i ? 'L' : 'M'}${px(a).toFixed(1)},${py(c).toFixed(1)}`).join(' ')
  const p10 = m.curve[10]
  return (
    <div>
      {v.sample_data && <div className="flag">These numbers come from the synthetic SAMPLE dataset. They show the test works; they say nothing about real Shurugwi ground.</div>}
      <div className="kpis">
        <Kpi label="Hold-out AUC" v={m.auc_holdout.toFixed(2)} d="0.50 = random choice of ground" />
        <Kpi label="Found in best 10% of ground" v={`${Math.round(m.capture_top10 * 100)}%`} d={`${m.n_test} held-out occurrences; random search finds 10%`} />
        <Kpi label="Found in best 20% of ground" v={`${Math.round(m.capture_top20 * 100)}%`} d="random search finds 20%" />
        <Kpi label="Training points" v={m.n_train} d={`${m.n_absences} confirmed blanks · train AUC ${m.auc_train?.toFixed(2)}`} />
      </div>
      <div className="vgrid">
        <div className="panel">
          <div className="label">Success-rate curve, model v{v.version}</div>
          <svg viewBox={`0 0 ${W} ${H}`} className="curve" role="img" aria-label="Share of held-out occurrences found against share of ground searched">
            {[0, .2, .4, .6, .8, 1].map((k) => <g key={k}>
              <line x1={L} x2={L + pw} y1={py(k)} y2={py(k)} className="grid" />
              <text x={L - 8} y={py(k) + 4} textAnchor="end" className="axis">{k * 100}%</text>
              <text x={px(k)} y={Tp + ph + 18} textAnchor="middle" className="axis">{k * 100}%</text></g>)}
            <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} className="diag" />
            <text x={px(.62)} y={py(.5)} className="axis">random choice</text>
            <path d={`${path} L${px(1)},${py(0)} L${px(0)},${py(0)} Z`} className="area" />
            <path d={path} className="line" />
            <circle cx={px(p10[0])} cy={py(p10[1])} r="5" className="dot" />
            <text x={px(p10[0]) + 10} y={py(p10[1]) + 4} className="axis b">{Math.round(p10[1] * 100)}% in best 10%</text>
            <text x={L + pw / 2} y={H - 6} textAnchor="middle" className="axis">Share of district searched, best-ranked ground first</text>
          </svg>
        </div>
        <div className="explain">
          <h2>How the test works</h2>
          <p><b>Spatial hold-out.</b> Occurrences south of {v.holdout_rule.value}° are never used for training. Random splits flatter a map because neighbouring points leak into the test.</p>
          <p><b>Skeptic check built in.</b> The test suite retrains on random fake occurrences and requires the hold-out AUC to fall back near 0.5. If it ever stays high, the validation is leaking.</p>
          <p><b>Field hit rate.</b> The real proof is week 10: the share of visited targets the geologist endorses, against sites chosen the usual way.</p>
        </div>
      </div>
    </div>
  )
}

function Kpi({ label, v, d }) {
  return <div className="kpi"><div className="label">{label}</div><div className="v">{v}</div><div className="small muted">{d}</div></div>
}
