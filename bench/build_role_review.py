"""Build a review-only speaker/character/addressee ledger; no translation or rendering."""
import csv
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'bench/runs/20261030/role-review'
JOB=ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1'

def save(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    voice=json.loads((OUT/'voice-evidence.json').read_text(encoding='utf-8'))
    regions=json.loads((JOB/'regions.json').read_text(encoding='utf-8'))
    chunks=[c for c in voice if c['timestamp'][1]<=60]
    assert len(chunks)==23
    # These facts were inspected on the contact sheets; they are NOT LLM or model recognition output.
    characters=[
        {'id':'CHAR_M','label_vi':'Người đàn ông đeo kính, áo vest','personal_name':None,
         'role_candidate':'Hiệu trưởng','role_status':'visually_and_contextually_supported_pending_review',
         'evidence':[{'frame':'frame-003.0.jpg','observation':'Nam đeo kính, áo vest ngồi cạnh người phụ nữ; khung này có câu 想死我了.'},
             {'frame':'frame-005.5.jpg','observation':'Người phụ nữ mở miệng trong lượt gọi 校长, hướng về người đàn ông cạnh cô.'},
             {'frame':'frame-093.0.jpg','observation':'Người đàn ông mở miệng khi phụ đề gọi người phụ nữ là 念念妈妈.'}]},
        {'id':'CHAR_F','label_vi':'Người phụ nữ mặc đồ xanh','personal_name':None,
         'role_candidate':'Phụ huynh; được gọi là mẹ Niệm Niệm','role_status':'visually_and_contextually_supported_pending_review',
         'evidence':[{'frame':'frame-009.5.jpg','observation':'Người phụ nữ trong lượt nói 我怕万一被我丈夫看见; transcript tự nhắc chồng, không chứng minh chồng là người đàn ông đang ngồi cạnh.'},
             {'frame':'frame-089.5.jpg','observation':'Người phụ nữ quay sang người đàn ông, phụ đề 那我家孩子学籍异常的事.'},
             {'frame':'frame-093.0.jpg','observation':'Người đàn ông đáp 念念妈妈, hỗ trợ vai mẹ/phụ huynh; không lấy tên đứa trẻ làm tên riêng của mẹ.'}]},
    ]
    save('characters.json',{'method':'assistant visual inspection + source discourse, no human audio listening or face recognition model',
        'characters':characters,'offscreen_references':[{'id':'REF_HUSBAND','role':'Chồng được nhắc trong lời thoại','seen':False,'not_assigned_as_listener':True},
            {'id':'REF_CHILD','role':'Con được nhắc; tên trên sub 念念','seen':False,'not_assigned_as_listener':True}],
        'relationship':'Người đàn ông được gọi 校长; người phụ nữ hỏi chuyện con. Không đủ căn cứ chốt hai người là vợ chồng/người yêu.',
        'approved_by_user':False})
    # Anchor association is a separate human/visual review operation after acoustic clustering.
    mapping={'SPK_00':'CHAR_M','SPK_01':'CHAR_F'}
    save('voice-character-map.json',{'status':'supported_candidate_mapping_not_user_approved',
        'method':'link independent acoustic clusters to visible speaking anchors, NOT automatic role recognition',
        'mappings':[{'speaker_cluster':'SPK_00','character_candidate':'CHAR_M','anchors':['ASR_0002','ASR_0034'],
                     'frames':['frame-003.0.jpg','frame-093.0.jpg']},
                    {'speaker_cluster':'SPK_01','character_candidate':'CHAR_F','anchors':['ASR_0003','ASR_0033'],
                     'frames':['frame-005.5.jpg','frame-089.5.jpg']}],
        'approved_by_user':False})
    pronouns={'version':1,'status':'proposed_not_approved','approved_by_user':False,
        'scope':{'start':0,'end':106.06,'scene':'same two-person scene'},
        'rationale':'Đề xuất trung tính theo vai hiệu trưởng/phụ huynh; không tự coi tiếp xúc thân mật là bằng chứng quan hệ tình cảm. Không thay toàn cục.',
        'directed_pairs':[{'speaker':'CHAR_M','listener':'CHAR_F','self':'tôi','address':'cô','register':'authority_to_parent',
            'notes':'Giữ sắc thái thân mật/kiểm soát bằng nội dung và nhịp; chưa tự đổi sang anh–em. Nếu xưng hô thay đổi phải ghi mốc và duyệt.'},
            {'speaker':'CHAR_F','listener':'CHAR_M','self':'tôi','address':'thầy','title':'thầy hiệu trưởng','register':'respectful_parent_to_principal',
             'notes':'Thầy–em là phương án văn phong khác cần duyệt riêng; không xem nguyên văn 您 là bằng chứng phải xưng em.'}],
        'unresolved_choices':['Chọn tôi–thầy hay em–thầy cho chiều phụ huynh→hiệu trưởng.',
            'Có cần đổi tôi–cô sang anh–em ở lượt nam hay không; nguồn hiện chưa đủ để khóa tự động.']}
    save('pronouns-proposed.json',pronouns)
    rows=[]
    queue=[{'id':'Q_PRONOUNS','kind':'directed_pronoun_approval','blocks_translation':True,
            'reason':'Hai chiều xưng hô mới là đề xuất, chưa được người dùng duyệt.'}]
    for c in chunks:
        index=c['asr_chunk_id'];start,end=c['timestamp'];candidate=mapping[c['speaker_cluster']]
        certain=c['acoustic_status']=='candidate'
        peer='CHAR_F' if candidate=='CHAR_M' else 'CHAR_M'
        flags=[]
        if not certain:
            flags.append('speaker_unresolved_short_or_weak_embedding')
        if index==3:
            flags.append('asr_4_to_5_88_vs_ocr_title_5_25_to_6_25_timing_review')
        if index in (4,7,19):
            flags.append('asr_视频_vs_burned_sub_饰品_do_not_silently_replace')
        if index==17:
            flags.append('asr_我怕_repeat_vs_single_ocr_我怕_requires_audio_review')
        if index==22:
            flags.append('source_pronoun_她_vs_visible_它_proposed_correction')
        ocr=[{'id':r['id'],'start':r['start'],'end':r['end'],'text':r['text']}
             for r in regions if r.get('kind')=='subtitle' and max(start,r['start'])<min(end,r['end'])]
        row={'id':f'ASR_{index:04d}','start':start,'end':end,'original_zh':c['text'],
            'speaker_label':c['speaker_cluster'] if certain else None,'speaker_candidate':c['speaker_cluster'],
            'character_speaker':candidate if certain else None,'character_speaker_candidate':candidate,
            'speaker_status':'supported_candidate_pending_review' if certain else 'uncertain',
            'listener_character':None,'listener_candidate':peer,
            'listener_status':'candidate_two_person_scene_pending_review' if certain else 'uncertain',
            'listener_evidence':'Direct title 校长 addresses CHAR_M.' if index==3 else 'Two-person scene and response sequence; no independently verified addressee label.',
            'acoustic_centroid_cosines':c['centroid_cosines'],'acoustic_margin':c['margin'],
            'confidence':'supported' if certain else 'uncertain','confidence_is_probability':False,
            'timing_status':'coarse_existing_asr_not_forced_aligned','ocr_reference':ocr,
            'flags':flags,'needs_review':True,'review_status':'awaiting_review',
            'translation_ready':False,'translation_blockers':['directed_pronoun_pair_not_approved','listener_not_confirmed']+([] if certain else ['speaker_not_confirmed']),
            'translated_vi':None}
        rows.append(row)
        if flags:
            queue.append({'id':'Q_'+row['id'],'cue_id':row['id'],'kind':'source_or_speaker_review','reasons':flags,'blocks_translation':True})
    save('utterances-review.json',rows)
    # Draft grouping uses candidate labels only; it never promotes uncertain individual cues.
    turns=[]
    for row in rows:
        if not turns or turns[-1]['speaker_candidate']!=row['speaker_candidate'] or row['start']-turns[-1]['end']>1.5:
            turns.append({'id':f'TURN_{len(turns)+1:03d}','start':row['start'],'end':row['end'],
                          'speaker_candidate':row['speaker_candidate'],'utterance_ids':[],'uncertain_utterances':[],
                          'status':'draft_pending_review','translation_ready':False})
        turn=turns[-1];turn['end']=row['end'];turn['utterance_ids'].append(row['id'])
        if row['speaker_status']=='uncertain':
            turn['uncertain_utterances'].append(row['id'])
    save('draft-turns.json',turns)
    save('source-correction-proposals.json',[
        {'id':'CORR_1','cue_id':'ASR_0022','asr':'有她在','proposed':'有它在','status':'proposed_pending_review',
         'evidence':['frame-052.0.jpg','OCR:51.75–52.5 有它在'],
         'meaning_note':'它 refers to a thing, not a woman; object likely the discussed video, not identity of another character.',
         'source_changed':False},
        {'id':'CORR_2','context_chunk_id':'ASR_0033','asr':'那我家孩子学习一场的事处理得怎么样了',
         'proposed':'那我家孩子学籍异常的事处理得怎么样了','status':'proposed_pending_review',
         'evidence':['frame-089.5.jpg','OCR88.25–91.0 那我家孩子学籍异常的事'],
         'source_changed':False},
        {'id':'CORR_3','context_chunk_id':'ASR_0035','asr':'孩子学节异常的事啊','proposed':'孩子学籍异常的事啊',
         'status':'proposed_pending_review','evidence':['frame-096.0.jpg'],'source_changed':False}])
    save('review-queue.json',queue)
    with (OUT/'utterances-review.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['ID','Start','End','Chinese','Speaker','Speaker candidate','Character','Character candidate','Listener','Listener candidate','Confidence','Review reasons','Translation ready'])
        for r in rows:
            writer.writerow([r['id'],r['start'],r['end'],r['original_zh'],r['speaker_label'],r['speaker_candidate'],
                r['character_speaker'],r['character_speaker_candidate'],r['listener_character'],r['listener_candidate'],r['confidence'],'; '.join(r['flags']),False])
    unresolved=sum(r['speaker_status']=='uncertain' for r in rows)
    save('manifest.json',{'source_job':JOB.name,'span_reviewed':[0,59],'context_span':[0,106.06],
        'asr_cues':23,'draft_turns':len(turns),'unresolved_acoustic_cues':unresolved,
        'source_video_sha256':hashlib.file_digest((JOB/'source.mp4').open('rb'),'sha256').hexdigest(),
        'source_asr_sha256':hashlib.sha256((JOB/'source-asr.json').read_bytes()).hexdigest(),
        'voice_model':json.loads((OUT/'voice-model-manifest.json').read_text()),
        'review_method':'assistant visual inspection of sampled stills and raw Chinese/OCR; ECAPA clustering over ASR chunks',
        'human_audio_listening_performed':False,'continuous_diarization_or_overlap_detection_performed':False,
        'voice_character_linking':'separate candidate mapping based on sampled visual anchors; not fully automatic',
        'listener_assignments_confirmed':0,'pronouns_user_approved':False,
        'translation_or_render_performed':False,'production_files_changed':False,
        'thresholds_are_uncalibrated':True})
    lines=['# Bảng duyệt lượt nói và xưng hô — chưa dịch', '',
        f'Video 7698707610815565097: bảng 0–59 giây, 23 cụm ASR, gom nháp thành {len(turns)} lượt. Đã đọc hình/ngữ cảnh đến 106 giây. Chưa sửa nguồn, dịch hoặc render; chưa đổi web.', '',
        '## Nhân vật có bằng chứng', '',
        '- CHAR_M: nam đeo kính/áo vest, được gọi校长; vai hiệu trưởng có bằng chứng. Chưa biết tên riêng.',
        '- CHAR_F: nữ mặc đồxanh, hỏi我家孩子 và được gọi念念妈妈; vai phụ huynh có bằng chứng. Chưa biết tên riêng của mẹ.',
        '- Chồng/con được nhắc nhưng không tự gán thành người nghe trong cảnh. Không chốt hai nhân vật là người yêu/vợchồng.', '',
        '## Xưng hô đề xuất để duyệt', '',
        '| Chiều | Xưng | Gọi | Trạng thái |','|---|---|---|---|',
        '| Hiệu trưởng → Phụ huynh | tôi | cô | Đề xuất, chưa khóa |',
        '| Phụ huynh → Hiệu trưởng | tôi | thầy / thầy hiệu trưởng | Đề xuất, chưa khóa |', '',
        '“Em–thầy” là lựa chọn văn phong có thể cân nhắc; chưa tự dùng. Không mặc định anh–em hoặc thay bạn–tôi toàn cục. File pronouns-proposed.json lưu từng chiều riêng, approved_by_user=false.', '',
        '## Giới hạn cần biết', '',
        f'Đã chạy model ECAPA local để gom 2 nhóm giọng trên các mốc ASR có sẵn; đây không phải diarization liên tục và chưa phát hiện chồng thoại. {unresolved}/23 cụm ngắn/yếu vẫn để nhãn xác nhận rỗng, dù có ứng viên. Cosine/margin không phải xác suất.',
        'Vai và nhãn giọng được nối riêng bằng đối chiếu khung hình; chưa có lượt nghe thủ công của người dùng. Khung tĩnh không chứng minh toàn bộ chuyển động miệng. Người nghe chỉ là candidate từ cảnh2người, chưa được xác nhận nên listener_character=null. Mọi câu translation_ready=false.',
        'Các timestamp vẫn là ASR thô; chưa có lip-sync hoặc căn từng từ. Không ép timing theo OCR: câu 校长 có chênh mốc ASR/OCR cần duyệt.', '',
        '## Lỗi nguồn có ảnh đối chiếu', '',
        '- 52 giây: ASR 有她在; hình ghi 有它在. Đề xuất sửa đại từ chỉ vật, không dịch thành “có cô ấy”. [Ảnh 52s](frame-052.0.jpg).',
        '- 89.5/96 giây: hình ghi 学籍异常 (hồ sơ/học tịch bất thường), ASR nhận sai 学习一场/学节异常. [Ảnh 89.5s](frame-089.5.jpg).',
        '- Một số phụ đề hình dùng 饰品 trong khi ASR ghi 视频. Giữ cả hai nguồn và đánh dấu cần nghe, chưa thay nguồn.', '',
        '## Bảng23cụm nguồn', '',
        'Người nói/người nghe trong ngoặc là ứng viên, chưa chốt. Dấu “?” giữ đúng nơi thiếu bằng chứng.', '',
        '| ID | Giây | Trung gốc | Nhãn giọng | Người nói | Người nghe | Cần duyệt |','|---|---|---|---|---|---|---|']
    label={'CHAR_M':'Hiệu trưởng','CHAR_F':'Phụ huynh'}
    reasons={'speaker_unresolved_short_or_weak_embedding':'Giọng ngắn/yếu, chưa xác nhận người nói',
        'asr_4_to_5_88_vs_ocr_title_5_25_to_6_25_timing_review':'Mốc ASR/OCR của 校长 khác nhau',
        'asr_视频_vs_burned_sub_饰品_do_not_silently_replace':'ASR 视频 khác chữ hình 饰品',
        'asr_我怕_repeat_vs_single_ocr_我怕_requires_audio_review':'ASR lặp 我怕, cần nghe lại',
        'source_pronoun_她_vs_visible_它_proposed_correction':'ASR 她 khác chữ hình 它'}
    for r in rows:
        speaker=label[r['character_speaker']] if r['character_speaker'] else '? ('+label[r['character_speaker_candidate']]+')'
        vals=[r['id'],f"{r['start']:g}–{r['end']:g}",r['original_zh'],r['speaker_label'] or '? ('+r['speaker_candidate']+')',
            speaker,'? ('+label[r['listener_candidate']]+')','; '.join(reasons[f] for f in r['flags']) or 'Duyệt người nghe/xưng hô; timing ASR thô']
        lines.append('| '+' | '.join(str(v).replace('|','/') for v in vals)+' |')
    lines+=['','## Bằng chứng và dữ liệu','',
        '[Khung hình1](evidence-sheet-1.jpg) · [Khung hình2](evidence-sheet-2.jpg) · [Khung hình3](evidence-sheet-3.jpg)',
        '[BảngJSON](utterances-review.json) · [CSV](utterances-review.csv) · [Lượt nói nháp](draft-turns.json) · [Hàng chờ duyệt](review-queue.json)',
        '', 'Chỉ khi chốt vai/người nghe/xưng hô và xử lý các cảnh báo nguồn mới cho các ID liên quan đi tiếp. Dữ liệu ở đây có hỗ trợ model và rà ảnh thủ công, chưa phải luồng tự động đầu-cuối.']
    (OUT/'REVIEW.md').write_text('\n'.join(lines),encoding='utf-8')
    freeze=subprocess.run([str(ROOT/'repo-tests/speaker-runtime/Scripts/python.exe'),'-m','pip','freeze'],capture_output=True,text=True)
    (OUT/'speaker-requirements-lock.txt').write_text(freeze.stdout,encoding='utf-8')
    print(json.dumps({'rows':len(rows),'draft_turns':len(turns),'unresolved_speaker_rows':unresolved,'translation_ready':0},ensure_ascii=False))

if __name__=='__main__':
    main()
