---
name: write-pg-verified
description: 娴犲簼绗傚〒鍛婂Η閼崇晫鏁撻幋鎰畱閺堫剙婀?JSON 閺傚洣娆㈡稉顓☆嚢閸欐牕銇?POI 閺嶇鐤勭紒鎾寸亯楠炶泛娲栭崘?PostgreSQL 閹存劖鐏夌悰銊ｂ偓鍌滄暏娴滃孩澧界悰灞芥礀鎼存挶鈧礁婀禒鍛絹娓?task_id 閸?search_directory 閺冩儼鍤滈崝銊︾叀閹靛墽鍌ㄥ鏇熸瀮娴犺绱濇禒銉ュ挤閸︺劑娓剁憰浣规闁俺绻?init 閸?verified 閸欏倹鏆熺憰鍡欐磰閸樼喎顫愮悰銊ょ瑢閺嶇鐤勯幋鎰亯鐞涖劌鎮曢敍娑橆洤閺嬫粌鎮撴稉鈧?task_id 閸ョ姾鐨熸惔锕傚櫢鐠囨洑楠囬悽鐔奉樋娑?index 閺傚洣娆㈤敍宀冨殰閸斻劍瀵滈張鈧弬鐗堟闂傚瓨鍩戦柅澶嬪閺堚偓閺傛壆绮ㄩ弸婧库偓?
---

# write-pg-verified

鐏忓棔绗傚〒鍛婄壋鐎圭偞濡ч懗鎴掗獓閸戣櫣娈?`index.json`閵嗕梗decision`閵嗕梗evidence`閵嗕梗record` 缁涘鏋冩禒璺哄鏉炶棄鎮楅敍灞藉晸閸?PostgreSQL 閻ㄥ嫭鐗崇€圭偞鍨氶弸婊嗐€冮敍灞借嫙閸氬本顒為弴瀛樻煀閸樼喎顫愮悰銊ф畱 `verify_status` 娑撹　鈧粌鍑￠弽绋跨杽閳ユ縿鈧?

## 瀹搞儰缍斿ù?

1. 娴兼ê鍘涢幒銉︽暪 `task_id + search_directory`閿涘矁鍤滈崝銊ユ躬閻╊喖缍嶆稉瀣偓鎺戠秺閺屻儲澹橀崠褰掑帳閻?index 閺傚洣娆㈤妴?
2. 鐎佃鐦℃稉顏勨偓娆撯偓?index 鐠囪褰囬弬鍥︽閸愬懎顔愰敍灞剧墡妤犲苯鍙炬稉顓犳畱 `task_id` 娑撳骸鍙嗛崣鍌欑閼锋番鈧?
3. 婵″倹鐏夐崥灞肩娑?`task_id` 閸涙垝鑵戞径姘嚋 index 閺傚洣娆㈤敍灞惧瘻閺傚洣娆㈤張鈧崥搴濇叏閺€瑙勬闂傛挳鈧瀚ㄩ張鈧弬鎵畱娑撯偓娑擃亷绱濋柆鍨帳鐠嬪啫瀹抽柌宥堢槸閸氬簼绮涚拠顖滄暏閺冄呯波閺嬫嚎鈧?
4. 娴犲酣鈧鑵戦惃?index 閸旂姾娴?`decision`閵嗕梗evidence`閵嗕梗record` 缁涘鍙ч懕鏃€鏋冩禒韬测偓?
5. 鏉烆剚宕茬€涙顔岄崥搴″晸閸?`verified` 閹稿洤鐣鹃惃鍕灇閺嬫粏銆冮敍灞借嫙閺囧瓨鏌?`init` 閹稿洤鐣鹃惃鍕斧婵銆冮妴?

## 鏉堟挸鍙嗛弬鐟扮础

姒涙顓荤悰銊ユ倳閿?
- `init = "poi_init"`
- `verified = "poi_verified"`

閹恒劏宕橀弬鐟扮础閿?

```python
from SKILL import execute

result = execute(
    {
        "task_id": "TASK_20260227_001",
        "search_directory": "output/results"
    },
    init="poi_init",
    verified="poi_verified"
)
```

娑旂喎褰叉禒銉ф纯閹恒儲鏂佹潻?data閿?

```python
from SKILL import execute

result = execute({
    "task_id": "TASK_20260227_001",
    "search_directory": "output/results",
    "init": "custom_poi_init",
    "verified": "custom_poi_verified"
})
```

閸忕厧顔愰弬鐟扮础閿?

```python
from SKILL import execute

result = execute({
    "task_id": "TASK_20260227_001",
    "index_file": "output/results/TASK_20260227_001/index.json",
    "init": "poi_init",
    "verified": "poi_verified"
})
```

閹靛綊鍣洪弬鐟扮础閿?

```python
from SKILL import execute_batch

results = execute_batch(
    ["TASK_001", "TASK_002", "TASK_003"],
    search_directory="output/results",
    init="poi_init",
    verified="poi_verified"
)

娑撳﹥鐖堕幎鈧懗钘夌安閻㈢喐鍨氱猾璁虫妧缂佹挻鐎敍?

```json
{
  "task_id": "TASK_20260227_001",
  "poi_id": "POI_12345",
  "files": {
    "decision": "decision_DEC_20260227_001.json",
    "evidence": "evidence_EVD_20260227_001.json",
    "record": "record_REC_20260227_001.json"
  },
  "poi_data": {
    "id": "POI_12345",
    "name": "閸栨ぞ鍚径褍顒熺粭顑跨閸栧娅?,
    "poi_type": "090101",
    "address": "閸栨ぞ鍚敮鍌濄偪閸╁骸灏憲澶哥矆鎼存挸銇囩悰?閸?,
    "city": "閸栨ぞ鍚敮?,
    "city_adcode": "110102",
    "x_coord": 116.3723,
    "y_coord": 39.9342
  }
}
```

韫囧懘娓剁€涙顔岄敍?
- `task_id`
- `poi_id`
- `files.decision`
- `poi_data`

## 婢?index 闁瀚ㄧ憴鍕灟

瑜版挷濞囬悽?`task_id + search_directory` 濡€崇础閺冭绱?

- 闁帒缍婇崠褰掑帳閸欘垵鍏橀惃?`index*.json`閿涘苯鑻熺憰鍡欐磰 Linux 娑撳顩?`.claude` 鏉╂瑧琚梾鎰閻╊喖缍嶆稉顓犳畱閸婃瑩鈧鏋冩禒?
- 閸欘亙绻氶悾娆愭瀮娴犺泛鍞寸€瑰綊鍣?`task_id` 娑撯偓閼峰娈戦崐娆撯偓?
- 婵″倹鐏夐張澶婎樋娑擃亜鈧瑩鈧绱濋幐澶嬫瀮娴犺埖娓堕崥搴濇叏閺€瑙勬闂傛挳妾锋惔蹇斿笓鎼?
- 娴ｈ法鏁ら張鈧弬鎵畱闁絼閲?index 缂佈呯敾閸ョ偛绨?

## 鐞涖劌鎮曢崣鍌涙殶

- `init`閿涙艾甯慨瀣€冮崥宥忕礉姒涙顓?`poi_init`
- `verified`閿涙碍鐗崇€圭偞鍨氶弸婊嗐€冮崥宥忕礉姒涙顓?`poi_verified`
- 閸忎浇顔忔导鐘猴紭鐞涖劌鎮曢敍灞肩瘍閸忎浇顔忔导鐘茬敨 schema 閻ㄥ嫬鑸板蹇ョ礉娓氬顩?`public.poi_init`
- 鐞涖劌鎮曟导姘粵閺嶅洩鐦戠粭锔界墡妤犲苯鎮楅崘宥嗗閸?SQL閿涘矂浼╅崗宥囨纯閹恒儱鐡х粭锔胯閹峰吋甯?

## 閸涙垝鎶ょ悰?
```bash
python SKILL.py <task_id> <search_directory>
python SKILL.py <index_file_path>
python SKILL.py --task-id <task_id> --search-directory <search_directory> [--init <init_table>] [--verified <verified_table>]
python SKILL.py --index-file <index_file_path> [--task-id <task_id>] [--init <init_table>] [--verified <verified_table>]
```
- 主入口 CLI 支持 `--init` 与 `--verified`，可覆盖默认表名。

```text
write-pg-verified/
閳规壕鏀㈤埞鈧?SKILL.md
閳规壕鏀㈤埞鈧?SKILL.py
閳规壕鏀㈤埞鈧?config/
閳?  閳规柡鏀㈤埞鈧?db_config.yaml
閳规柡鏀㈤埞鈧?scripts/
    閳规壕鏀㈤埞鈧?__init__.py
    閳规壕鏀㈤埞鈧?file_loader.py
    閳规壕鏀㈤埞鈧?data_converter.py
    閳规壕鏀㈤埞鈧?db_writer.py
    閳规柡鏀㈤埞鈧?logger_config.py

- 閹恒劏宕樻导妯哄帥娴ｈ法鏁?`task_id + search_directory`閿涘矁顔€閹垛偓閼冲€熷殰瀹稿崬鐣幋?index 閸欐垹骞囨稉搴ㄥ櫢鐠囨洜绮ㄩ弸婊冨幑鎼存洏鈧?
- 婵″倹鐏夋担鐘插嚒缂佸繑妲戠涵顔剧叀闁捁顩﹂崘娆忔礀閸濐亙绔存禒鐣岀波閺嬫粣绱濋崣顖欎簰閻╁瓨甯存导?`index_file`閿涘本顒濋弮鏈电瑝娴兼艾寮稉搴樷偓婊勬付閺?index閳ユ繈鈧瀚ㄩ妴?
- 閹垛偓閼虫垝绻氶幐浣哥畵缁涘绱癭verified` 鐞涖劌鍑＄€涙ê婀惄绋挎倱 `task_id` 閺冭绱濇稉宥夊櫢婢跺秵褰冮崗銉礉娴ｅ棔绮涙导姘纯閺?`init` 鐞涖劎濮搁幀浣碘偓?
- 閺冦儱绻旀导姘愁唶瑜版洖鈧瑩鈧?index 閺佷即鍣洪妴浣规付缂佸牆鎳℃稉顓犳畱閺堚偓閺傜増鏋冩禒璁圭礉娴犮儱寮烽張顒侇偧鐎圭偤妾崘娆忓弳閻ㄥ嫯銆冮崥宥忕礉娓氬じ绨幒鎺撶叀闂傤噣顣介妴淇橮ath.rglob(...)` 闁帒缍婇弻銉﹀閸欘垵顩惄?Linux 娑?`.claude` 缁涘娈ｉ挊蹇曟窗瑜版洏鈧?

## 閸ョ偛绨辩€涙顔岄弶銉︾爱缁撅附娼?

- `verification_notes` 娴犲懏娼甸懛?`decision.overall.summary`閿涘矁顩﹀Ч鍌欑瑐濞撳憡褰佹笟娑毲旂€规氨娈戞稉顓熸瀮閹芥顩﹂妴?
- `changes_made` 娴兼ê鍘涙担璺ㄦ暏 `record.verification_result.changes`閿涘奔绗夐崘宥囨纯閹恒儰绶风挧鏍殰閻㈣鲸鐗稿蹇曟畱 `decision.corrections`閵?
- 閹存劖鐏夌悰銊よ厬閻?`name`閵嗕梗x_coord`閵嗕梗y_coord`閵嗕梗poi_type`閵嗕梗address`閵嗕梗city`閵嗕梗city_adcode` 閸у洣浜?`record.verification_result.final_values` 娑撳搫鍣妴?
- 婵″倹鐏?`record.verification_result.final_values` 閺堫亝顒滅涵顔荤秼閻滅増鐗崇€圭偛鎮楅惃鍕付缂佸牆鈧》绱濇惔鏃囶潒娑撹桨绗傚〒鍝ョ波閺嬫粈绗夐崥鍫熺壐閿涘瞼顩﹀銏犳礀鎼存挶鈧?
