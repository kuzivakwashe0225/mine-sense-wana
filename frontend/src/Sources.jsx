export default function Sources({ meta }) {
  const coef = Object.fromEntries(meta.features.map((f, i) => [f, meta.coef_mean[i]]))
  return (
    <div data-reading>
      <h2>Evidence layers in model v{meta.version}</h2>
      <p className="muted">Every layer carries its source and whether it is real or sample data. Weight is the model's average coefficient on the standardised layer: larger means more influence on the ranking.</p>
      <div className="tablewrap"><table>
        <thead><tr><th>Layer</th><th>Source</th><th>Coverage</th><th>Weight</th><th>Data</th></tr></thead>
        <tbody>{Object.entries(meta.provenance).map(([k, p]) => (
          <tr key={k}><td>{p.label}</td><td>{p.source}</td><td className="mono">{Math.round(p.coverage * 100)}%</td>
            <td className="mono">{coef[k]?.toFixed(2)}</td><td>{p.sample ? <span className="st pending">SAMPLE</span> : <span className="st endorsed">real</span>}</td></tr>
        ))}</tbody>
      </table></div>
      <p className="small muted">Wana shows places worth checking. It does not prove a resource and does not confer mining rights. Fieldwork only on authorised ground.</p>
    </div>
  )
}
