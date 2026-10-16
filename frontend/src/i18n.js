// Miner-facing text. ChiShona is a working draft: have Shona-speaking miners review it before fieldwork.
export const T = {
  en: {
    chance: 'Wana score', conf: 'Confidence', why: 'Why it ranks here', against: 'What counts against it',
    check: 'What to check first', safety: 'Safety', rights: 'Mineral rights', location: 'Location',
    plan: 'Plan a field check', topPct: (p) => `Top ${p}% of the district`, rank: (r, n) => `Rank ${r} of ${n}`, cell: 'Map point',
    // field app
    fieldTitle: 'Wana Field', online: 'Online', offline: 'Offline', target: 'Target', newLoc: 'New location (not a target)',
    gps: 'Location', capture: 'Use phone GPS', locating: 'Finding position…', acc: 'accuracy', manual: 'or type coordinates',
    gpsErr: 'Could not get a GPS fix. Go outside, wait a minute and try again, or type the coordinates.',
    seeQ: 'What do you see?', yes: 'Yes', tapYes: 'Tap if yes',
    q: { black_grains: 'Black shiny grains', heavy: 'Feels very heavy', brown_streak: 'Brown streak on tile', green_host: 'Green soapy rock nearby', old_pits: 'Old pits or shafts nearby' },
    photo: 'Photo of the rock', addPhoto: 'Take or add photo', sample: 'Sample bag number', notes: 'Notes', notesPh: 'e.g. float on ridge, 2 m wide',
    observer: 'Your name or group', save: 'Save record', sync: 'Send now', needLoc: 'Add a location first.',
    savedOffline: 'Saved on this phone. It will be sent when there is network.', sentOk: 'Sent to the geologist for review.',
    rules: 'Surface samples only. No pits or trenches. Authorised ground only.', outbox: 'Records on this phone',
    needSignIn: 'Saved on this phone. Sign in to send it to the geologist.', signInToSend: 'Sign in to send',
    st: { queued: 'waiting to send', sent: 'sent', error: 'send failed, will retry', rejected: 'not accepted', auth: 'waiting for sign-in' },
  },
  sn: {
    chance: 'Mamaki eWana', conf: 'Kuvimba kwedu', why: 'Sei nzvimbo iyi yakakwira', against: 'Zvinodzikisa mukana',
    check: 'Zvekutanga kutarisa', safety: 'Kuchengetedzeka', rights: 'Kodzero dzekuchera', location: 'Nzvimbo',
    plan: 'Ronga kuenda kumunda', topPct: (p) => `Pakati pe${p}% yepamusoro mudunhu`, rank: (r, n) => `Nhamba ${r} pa${n}`, cell: 'Nzvimbo pamepu',
    fieldTitle: 'Wana Field', online: 'Ine network', offline: 'Hapana network', target: 'Nzvimbo yakarongwa', newLoc: 'Nzvimbo itsva',
    gps: 'Nzvimbo', capture: 'Shandisa GPS yefoni', locating: 'Kutsvaga nzvimbo…', acc: 'kurongeka', manual: 'kana nyorai nhamba',
    gpsErr: 'GPS haina kushanda. Budai panze, mirai kwechinguva moedza zvakare, kana nyorai nhamba.',
    seeQ: 'Munoona chii?', yes: 'Hongu', tapYes: 'Baya kana hongu',
    q: { black_grains: 'Zvidimbu zvitema zvinopenya', heavy: 'Rinorema zvikuru', brown_streak: 'Rinosiya mutsetse webrown', green_host: 'Dombo regirini rinotsvedza riri pedyo', old_pits: 'Makomba ekare ari pedyo' },
    photo: 'Mufananidzo wedombo', addPhoto: 'Tora mufananidzo', sample: 'Nhamba yebhegi resample', notes: 'Zvamaona', notesPh: 'semuenzaniso: zvidimbu pagomo, 2 m',
    observer: 'Zita renyu kana boka', save: 'Chengetedza', sync: 'Tumira izvozvi', needLoc: 'Isai nzvimbo kutanga.',
    savedOffline: 'Zvachengetwa pafoni. Zvichatumirwa kana network yauya.', sentOk: 'Zvatumirwa kugeologist.',
    rules: 'Samples dzepamusoro chete. Musachera makomba. Pavhu rakabvumidzwa chete.', outbox: 'Zviri pafoni ino',
    needSignIn: 'Zvachengetwa pafoni. Pinda muakaundi kuti zvitumirwe kugeologist.', signInToSend: 'Pinda kuti utumire',
    st: { queued: 'zvakamirira kutumirwa', sent: 'zvatumirwa', error: 'hazvina kuenda, zvichaedzwa zvakare', rejected: 'hazvina kugamuchirwa', auth: 'zvakamirira kupinda' },
  },
}
export const CHECK_KEYS = ['black_grains', 'heavy', 'brown_streak', 'green_host', 'old_pits']
