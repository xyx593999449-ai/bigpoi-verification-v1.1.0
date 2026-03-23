# Product CHANGELOG

## [Unreleased]

### Changed
- write-pg-verified/SKILL.py main entry now supports --init and --verified for table override.
- Keeps backward-compatible CLI modes (<task_id> <search_directory> and <index_file_path>).

### Docs
- Updated write-pg-verified/SKILL.md command examples with --init / --verified.
- Updated Product/README.md to mention CLI table-override support.

### Process
- Backed up current docs to docs/backups/20260323-112956-177/ before this update.

## [1.6.10] - 2026-03-17

### Fixed
- 闁告牕鎼崹搴ㄥ矗椤栨粍绾柟鎭掑劜婢х晫鎮板畝鈧▓鎴﹀礂閵夈儱缍撻柤瀛樼濠€鐗堢▔鎼存繄鐭屽〒姘☉閸炴挳鏌?import 闁?helper module闁挎稑鐭傛导鈺呭礂瀹ュ棗惟 `run_context.py` 閻犲浂鍨扮紞瀣箣?CLI 闁煎瓨纰嶅﹢浼村Υ?

## [1.6.9] - 2026-03-16

### Fixed
- 缂備胶鍠嶇粩?`run_context` 闁汇劌瀚悾鐐媴瀹ュ嫮鐟㈤悹瀣暟閺併倝寮悷鎵闁挎稑濂旈幈銊ヮ潰閿濆拋妯嬪璺哄閸撳ジ寮甸鈧顔芥交閹邦垼鏀藉☉鎾筹梗缁楀懘寮崶顏嗙闁告柡鏅滆啯闁秆勵殘濞堟垵顕ｉ弴鐘虫殢闁?

## [1.6.8] - 2026-03-16

### Changed
- 閻?`location` 闁瑰嘲妫楅崹搴㈢▔?`address` 濞?`coordinates` 濞戞挶鍊撻柌婊堝冀閹间胶宕ｇ紓浣规綑鐎规娊鏁嶇仦鍊熷珯闁告艾鏈鐐哄即鐎涙ɑ鐓€ schema闁靛棔绶氬Σ鍥磹閻撳孩瀚查柛銉у仜缁ㄩ亶寮伴悩鑼闁?

## [1.6.7] - 2026-03-13

### Fixed
- 閻炴稏鍎卞?`decision.corrections`闁靛棔姊梖inal_values` 濞?`changes` 闁汇劌瀚禒鍫ュ礉閵娿儱鏅搁柛鎴炴そ閳ь剚妲掔欢顐﹀Υ?

## [1.6.6] - 2026-03-13

### Changed
- 鐎殿喗娲栭崣?`run_id` 闂傚懏姊婚‖鍥嫉閸濆嫬鐓戦柨娑樻湰濡叉垹娑?`output/runs/{run_id}` 閺夆晛娲ㄩ埢濂告儎椤旇偐绉块柛?staging 闁烩晩鍠栫紞宥夊Υ?

## [1.6.5] - 2026-03-10

### Changed
- 缂備胶鍠嶇粩?`WorkspaceRoot` 濞戞挸娴风划銊╁几濠婂懏绐楃憸鐗堟礉琚欓柡瀣姍閳ь剚妲掔欢顐︽晬鐏炵瓔鏉荤€殿噣缂氬▔鏇㈡儎椤旇偐绉块柟绗涘棭鏀介柣銊ュ鑿欓悗瑙勭閳ь儸浣插亾?

## [1.6.4] - 2026-03-10

### Fixed
- 濞ｅ浂鍠楅?`write-pg-verified` 闁革负鍔庨崒銊ヮ嚕閺囩偛绲洪柣婊堫暒缁楀瞼绱掗幘瀵镐函闁搞儳鍋涢崯鎾寸▔椤撶姵鐣遍悹渚灠缁剁偤姊婚鈧。浠嬪Υ?

## [1.6.3] - 2026-03-10

### Changed
- 濠⒀呭仜瀹?`write-pg-verified` 闁汇劌瀚ú鏍ㄦ償閹惧瓨衼閻忓繐瀚粭宀€妲愰姀鐘电┛閻熸瑱绲鹃悗浠嬫嚄閽樺顫旈柕?

## [1.6.2] - 2026-03-10

### Fixed
- 濞ｅ浂鍠楅婊堝春鏉炴壆鑹?`task_id + search_directory` 闁?`index` 闁哄被鍎叉竟姗€鏌呴弰蹇曞竼闁?

## [1.1.1] - 2026-02-12

### Optimized
- 濞村吋锚鐎?evidence source 闂佹澘绉堕悿鍡欑磼閸曨厾鐭忓☉?Token 婵炴垵鐗愰埀顒侇殕鐢爼宕氶煬娴嬪亾?

## [1.1.0] - 2026-02-10

### Breaking Change
- 鐟滆埇鍨洪崹?`skills-bigpoi-verification / evidence-collection / verification` 闁汇劌瀚俊褔鎳楅懞銉ヮ€曢柛鎺戞缁劑寮搁崟鈹惧亾?

## [1.0.2] - 2026-02-04

### Fixed
- 濞ｅ浂鍠栭ˇ鍙夊緞濮橆厾鐖遍悹鍥︾劍瀹撲線鏌岄崶顒佽偁闂佺偓宕橀惌鐐▔椤撶姵鐣遍悹瀣暟閺併倖绋夋惔锛勭＝閻㈩垳顭堥ˇ鈺呮偠閸℃稒锛栧Λ鐗埱滈埀?

## [1.0.1] - 2026-02-03

### Fixed
- 濞ｅ浂鍠栭ˇ鏌ュ籍閳哄倹鍩傞梺鏉跨Ф閻ゅ棝寮崶锔筋偨闁告稖妫勯幃鏇熺▔鎼达紕绌块柣顫姂濡埖锛愬Ο绯曞亾?

