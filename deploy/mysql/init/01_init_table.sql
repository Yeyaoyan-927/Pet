CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> bae2921eeb04

CREATE TABLE appointment (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_no VARCHAR(32) NOT NULL COMMENT '预约单号', 
    user_id BIGINT NOT NULL COMMENT '宠主 ID', 
    pet_id BIGINT NOT NULL COMMENT '宠物 ID', 
    service_type VARCHAR(32) NOT NULL COMMENT '洗护服务类型', 
    appoint_date DATE NOT NULL COMMENT '预约日期', 
    slot_time VARCHAR(10) NOT NULL COMMENT '预约时段 HH:00', 
    status VARCHAR(32) NOT NULL COMMENT '预约状态', 
    staff_id BIGINT COMMENT '归属店员', 
    operator_staff_id BIGINT COMMENT '代客预约操作店员', 
    created_by VARCHAR(16) NOT NULL COMMENT '入口：form 表单 / agent 对话 / staff 代客', 
    temp_phone_encrypted VARCHAR(255) COMMENT '代客预约临时用户手机号密文', 
    idempotent_key VARCHAR(64) COMMENT '双入口统一幂等键', 
    remark TEXT COMMENT '宠主备注', 
    cancel_reason VARCHAR(255) COMMENT '取消原因', 
    terminate_reason VARCHAR(255) COMMENT '异常终止原因', 
    reschedule_times SMALLINT NOT NULL COMMENT '已改期次数', 
    risk_level VARCHAR(16) COMMENT '风险等级快照', 
    confirm_at DATETIME COMMENT '店员确认时间', 
    arrive_at DATETIME COMMENT '到店时间', 
    start_at DATETIME COMMENT '开始洗护时间', 
    finish_at DATETIME COMMENT '洗护完成时间', 
    cancel_at DATETIME COMMENT '取消时间', 
    deleted_at DATETIME COMMENT '逻辑删除时间', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (idempotent_key), 
    UNIQUE (order_no)
);

CREATE INDEX idx_appt_date_slot_status ON appointment (appoint_date, slot_time, status);

CREATE INDEX idx_appt_user_status ON appointment (user_id, status);

CREATE INDEX ix_appointment_pet_id ON appointment (pet_id);

CREATE INDEX ix_appointment_staff_id ON appointment (staff_id);

CREATE INDEX ix_appointment_status ON appointment (status);

CREATE INDEX ix_appointment_user_id ON appointment (user_id);

CREATE TABLE message (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    user_id BIGINT NOT NULL COMMENT '接收用户', 
    title VARCHAR(120) NOT NULL COMMENT '标题', 
    content TEXT COMMENT '内容', 
    msg_type VARCHAR(32) NOT NULL COMMENT '消息类型', 
    biz_id BIGINT COMMENT '关联业务 ID', 
    is_read SMALLINT NOT NULL COMMENT '1 已读', 
    read_at DATETIME COMMENT '已读时间', 
    deleted_at DATETIME COMMENT '逻辑删除时间', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_message_user_id ON message (user_id);

CREATE TABLE operation_log (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    user_id BIGINT COMMENT '操作账号 ID', 
    staff_id BIGINT COMMENT '操作店员 ID', 
    module VARCHAR(32) NOT NULL COMMENT '业务模块', 
    action VARCHAR(64) NOT NULL COMMENT '操作动作', 
    biz_id BIGINT COMMENT '业务主键', 
    before_snapshot TEXT COMMENT '操作前 JSON 快照', 
    after_snapshot TEXT COMMENT '操作后 JSON 快照', 
    ip VARCHAR(64) COMMENT '客户端 IP', 
    user_agent VARCHAR(255) COMMENT 'User-Agent', 
    status SMALLINT NOT NULL COMMENT '1 成功 / 0 失败', 
    detail VARCHAR(500) COMMENT '补充说明', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_operation_log_staff_id ON operation_log (staff_id);

CREATE INDEX ix_operation_log_user_id ON operation_log (user_id);

CREATE TABLE pet (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    user_id BIGINT NOT NULL COMMENT '归属宠主', 
    staff_id BIGINT COMMENT '归属店员（本人服务客户）', 
    name VARCHAR(50) NOT NULL COMMENT '宠物名', 
    species VARCHAR(20) NOT NULL COMMENT 'dog / cat', 
    breed VARCHAR(50) COMMENT '品种', 
    gender VARCHAR(10) NOT NULL COMMENT 'male / female', 
    birthday DATE COMMENT '生日', 
    weight NUMERIC(5, 2) COMMENT '体重 kg', 
    sterilized SMALLINT NOT NULL COMMENT '是否绝育', 
    allergy TEXT COMMENT '过敏史', 
    skin_disease TEXT COMMENT '皮肤病史', 
    stress_level SMALLINT NOT NULL COMMENT '应激等级 0 无 / 1 轻 / 2 中 / 3 重', 
    aggressive SMALLINT NOT NULL COMMENT '攻击倾向标记', 
    emergency_contact VARCHAR(50) COMMENT '应急联系人', 
    emergency_phone VARCHAR(255) COMMENT '应急联系电话（AES 密文）', 
    remark TEXT COMMENT '备注', 
    deleted_at DATETIME COMMENT '逻辑删除时间', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_pet_staff_id ON pet (staff_id);

CREATE INDEX ix_pet_user_id ON pet (user_id);

CREATE TABLE risk_report (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    appointment_id BIGINT NOT NULL COMMENT '预约 ID', 
    pet_id BIGINT NOT NULL COMMENT '宠物 ID', 
    risk_level VARCHAR(16) NOT NULL COMMENT 'high / low / none', 
    engine_type VARCHAR(16) NOT NULL COMMENT 'rule / llm', 
    risk_items TEXT COMMENT '命中风险项，JSON 数组', 
    ai_summary TEXT COMMENT '风险摘要', 
    knowledge_refs TEXT COMMENT '引用知识片段，JSON 数组', 
    suggestion TEXT COMMENT '处置建议', 
    confirmed SMALLINT NOT NULL COMMENT '店员是否已复核', 
    confirmed_by BIGINT COMMENT '复核店员 ID', 
    confirmed_at DATETIME COMMENT '复核时间', 
    handle_measure TEXT COMMENT '店员处置措施', 
    invalidated SMALLINT NOT NULL COMMENT '1 表示因预约超时取消而失效', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_risk_report_appointment_id ON risk_report (appointment_id);

CREATE INDEX ix_risk_report_pet_id ON risk_report (pet_id);

CREATE TABLE store_setting (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    setting_key VARCHAR(64) NOT NULL COMMENT '配置键', 
    setting_value VARCHAR(255) NOT NULL COMMENT '配置值（字符串存储）', 
    value_type VARCHAR(16) NOT NULL COMMENT 'int / bool / string', 
    default_value VARCHAR(255) NOT NULL COMMENT '默认值，非法时回退', 
    setting_desc VARCHAR(255) COMMENT '中文说明', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (setting_key)
);

CREATE TABLE sys_user (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    username VARCHAR(50) NOT NULL COMMENT '登录账号', 
    password_hash VARCHAR(255) NOT NULL COMMENT 'bcrypt 哈希', 
    real_name VARCHAR(50) COMMENT '姓名 / 昵称', 
    phone_encrypted VARCHAR(255) COMMENT '手机号 AES 密文', 
    phone_hash VARCHAR(64) COMMENT '手机号 HMAC 索引，用于查重', 
    `role` VARCHAR(20) NOT NULL COMMENT 'customer / staff / manager', 
    status SMALLINT NOT NULL COMMENT '1 启用 / 0 禁用', 
    is_temp SMALLINT NOT NULL COMMENT '1 表示代客预约创建的临时用户', 
    last_login_at DATETIME COMMENT '最后登录时间', 
    deleted_at DATETIME COMMENT '逻辑删除时间', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (username)
);

CREATE INDEX ix_sys_user_phone_hash ON sys_user (phone_hash);

CREATE INDEX ix_sys_user_role ON sys_user (`role`);

CREATE TABLE vaccine_record (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    pet_id BIGINT NOT NULL COMMENT '宠物 ID', 
    record_type VARCHAR(20) NOT NULL COMMENT 'vaccine 疫苗 / deworm_inner 体内驱虫 / deworm_outer 体外驱虫', 
    name VARCHAR(100) COMMENT '疫苗 / 药品名称', 
    record_date DATE NOT NULL COMMENT '本次接种 / 驱虫日期', 
    next_date DATE COMMENT '下次建议日期', 
    remark VARCHAR(255) COMMENT '备注', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_vaccine_record_pet_id ON vaccine_record (pet_id);

CREATE TABLE wash_record (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    appointment_id BIGINT NOT NULL COMMENT '预约 ID', 
    pet_id BIGINT NOT NULL COMMENT '宠物 ID', 
    staff_id BIGINT COMMENT '执行店员', 
    service_type VARCHAR(32) NOT NULL COMMENT '服务类型', 
    wash_start DATETIME COMMENT '开始时间', 
    wash_end DATETIME COMMENT '结束时间', 
    skin_condition TEXT COMMENT '洗护后皮肤状况', 
    hair_condition TEXT COMMENT '毛发状况', 
    products VARCHAR(255) COMMENT '使用产品', 
    staff_note TEXT COMMENT '店员记录', 
    photo_paths TEXT COMMENT '照片相对路径，JSON 数组字符串', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (appointment_id)
);

CREATE INDEX ix_wash_record_pet_id ON wash_record (pet_id);

CREATE INDEX ix_wash_record_staff_id ON wash_record (staff_id);

INSERT INTO alembic_version (version_num) VALUES ('bae2921eeb04');

-- Running upgrade bae2921eeb04 -> 2abbc7d620d2

CREATE TABLE chat_message (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    session_id BIGINT NOT NULL COMMENT '会话 ID', 
    user_id BIGINT COMMENT '消息归属用户', 
    `role` VARCHAR(16) NOT NULL COMMENT 'user / assistant / tool / system', 
    content TEXT COMMENT '消息内容（已脱敏）', 
    intent VARCHAR(32) COMMENT '识别出的意图', 
    tool_name VARCHAR(64) COMMENT '工具名', 
    tool_args TEXT COMMENT '工具入参 JSON', 
    tool_result TEXT COMMENT '工具出参 JSON', 
    step SMALLINT NOT NULL COMMENT 'ReAct 轮次', 
    model VARCHAR(64) COMMENT '使用的模型名', 
    latency_ms INTEGER COMMENT '耗时（毫秒）', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_chat_message_session_id ON chat_message (session_id);

CREATE TABLE chat_session (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    user_id BIGINT NOT NULL COMMENT '会话归属用户', 
    title VARCHAR(120) NOT NULL COMMENT '会话标题', 
    status VARCHAR(16) NOT NULL COMMENT 'active / closed', 
    pending_action TEXT COMMENT '待二次确认的写操作，JSON 字符串', 
    turn_count INTEGER NOT NULL COMMENT '对话轮次', 
    last_message_at DATETIME COMMENT '最后消息时间', 
    deleted_at DATETIME COMMENT '逻辑删除时间', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_chat_session_user_id ON chat_session (user_id);

UPDATE alembic_version SET version_num='2abbc7d620d2' WHERE alembic_version.version_num = 'bae2921eeb04';

-- Running upgrade 2abbc7d620d2 -> 916b67aae47e

CREATE TABLE knowledge_entry (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    category VARCHAR(32) NOT NULL COMMENT '分类：allergy 过敏原 / skin 皮肤病 / stress 应激 / drug 用药 / senior 老年 / behavior 行为', 
    title VARCHAR(120) NOT NULL COMMENT '知识标题', 
    content TEXT NOT NULL COMMENT '知识正文（洗护注意事项）', 
    tags VARCHAR(255) COMMENT '检索标签，逗号分隔；与规则引擎的 risk_key、宠物档案字段名对齐', 
    keywords VARCHAR(255) COMMENT '补充关键词，逗号分隔', 
    species VARCHAR(16) NOT NULL COMMENT 'dog / cat / all', 
    source VARCHAR(120) COMMENT '来源说明（便于门店追溯与替换）', 
    enabled SMALLINT NOT NULL COMMENT '1 启用', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_knowledge_entry_category ON knowledge_entry (category);

CREATE TABLE slot_lock (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    appoint_date DATE NOT NULL COMMENT '预约日期', 
    slot_time VARCHAR(5) NOT NULL COMMENT '时段 HH:00', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    CONSTRAINT uk_slot_lock_date_time UNIQUE (appoint_date, slot_time)
);

CREATE TABLE task_run (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    name VARCHAR(64) NOT NULL COMMENT '任务名（与 JOBS 注册表一致）', 
    last_started_at DATETIME COMMENT '上次开始时间', 
    last_finished_at DATETIME COMMENT '上次结束时间', 
    last_status VARCHAR(16) NOT NULL COMMENT 'success / failed / skipped / pending', 
    last_summary VARCHAR(255) COMMENT '上次执行结果摘要', 
    last_trigger VARCHAR(16) NOT NULL COMMENT 'schedule 调度触发 / manual 手动触发', 
    run_count INTEGER NOT NULL COMMENT '累计执行次数', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (name)
);

UPDATE alembic_version SET version_num='916b67aae47e' WHERE alembic_version.version_num = '2abbc7d620d2';

-- Running upgrade 916b67aae47e -> 4f280147a257

CREATE TABLE boarding_care_log (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_id BIGINT NOT NULL COMMENT '寄养订单 ID', 
    log_date DATE NOT NULL COMMENT '日志日期', 
    eating VARCHAR(64) COMMENT '进食：正常 / 偏少 / 拒食 + 份量', 
    drinking VARCHAR(32) COMMENT '饮水：正常 / 偏少 / 偏多', 
    stool VARCHAR(64) COMMENT '排便：次数与性状', 
    spirit VARCHAR(32) COMMENT '精神：活泼 / 正常 / 萎靡 / 焦躁', 
    activity VARCHAR(64) COMMENT '活动量：遛放次数与时长', 
    abnormal SMALLINT NOT NULL COMMENT '是否异常：1 是（触发即时推送 + 店长关注）', 
    abnormal_note VARCHAR(255) COMMENT '异常描述', 
    photos VARCHAR(512) COMMENT '照片地址，逗号分隔（每日至少 1 张）', 
    sop_checked VARCHAR(255) COMMENT '已完成的 SOP 检查项，逗号分隔', 
    staff_id BIGINT COMMENT '记录人', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_boarding_care_log_log_date ON boarding_care_log (log_date);

CREATE INDEX ix_boarding_care_log_order_id ON boarding_care_log (order_id);

CREATE TABLE boarding_care_plan (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_id BIGINT NOT NULL COMMENT '寄养订单 ID', 
    item_type VARCHAR(16) NOT NULL COMMENT 'medication 用药 / feeding 喂食 / walk 遛放 / taboo 禁忌', 
    content VARCHAR(255) NOT NULL COMMENT '内容（药名剂量 / 要求）', 
    frequency VARCHAR(64) COMMENT '频次，如 每日 2 次', 
    need_staff SMALLINT NOT NULL COMMENT '需店员操作：1 是', 
    sort_no INTEGER NOT NULL COMMENT '排序', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_boarding_care_plan_order_id ON boarding_care_plan (order_id);

CREATE TABLE boarding_order (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_no VARCHAR(32) NOT NULL COMMENT '寄养单号', 
    user_id BIGINT NOT NULL COMMENT '宠主 ID', 
    pet_id BIGINT NOT NULL COMMENT '宠物 ID', 
    room_id BIGINT NOT NULL COMMENT '宠舍 ID', 
    room_type VARCHAR(20) NOT NULL COMMENT '房型快照', 
    status VARCHAR(24) NOT NULL COMMENT '寄养状态', 
    check_in_date DATE NOT NULL COMMENT '入住日期', 
    check_out_date DATE NOT NULL COMMENT '离店日期', 
    nights INTEGER NOT NULL COMMENT '寄养晚数', 
    feeding_plan VARCHAR(16) NOT NULL COMMENT 'self / standard / premium / prescription', 
    food_note VARCHAR(255) COMMENT '自备食物明细与喂食说明', 
    shipping_method VARCHAR(16) NOT NULL COMMENT 'self 自送 / pickup 上门接 / return 送宠到家', 
    shipping_address VARCHAR(255) COMMENT '接送地址', 
    shipping_slot VARCHAR(32) COMMENT '上门时间段，如 10:00-12:00', 
    shipping_fee_cents INTEGER NOT NULL COMMENT '接送费（分）', 
    daily_fee_cents INTEGER NOT NULL COMMENT '日均费用（分）', 
    subtotal_cents INTEGER NOT NULL COMMENT '房费小计（分）', 
    discount_percent INTEGER NOT NULL COMMENT '已应用折扣百分比（100=无折扣，90=9 折）', 
    extra_fee_cents INTEGER NOT NULL COMMENT '增值项（分）', 
    total_cents INTEGER NOT NULL COMMENT '应付总额（分）', 
    settle_note VARCHAR(255) COMMENT '结算说明（提前接回 / 延期等）', 
    vaccine_ok SMALLINT NOT NULL COMMENT '下单时疫苗是否完整：1 是', 
    vaccine_note VARCHAR(255) COMMENT '疫苗校验说明', 
    isolate_required SMALLINT NOT NULL COMMENT '需隔离观察（皮肤病史等）：1 是', 
    risk_level VARCHAR(16) COMMENT '下单时风险等级快照', 
    emergency_contact VARCHAR(50) COMMENT '紧急联系人', 
    emergency_phone_encrypted VARCHAR(255) COMMENT '紧急联系电话（AES 密文）', 
    medical_authorized SMALLINT NOT NULL COMMENT '授权就医：1 是', 
    terms_confirmed_at DATETIME COMMENT '条款确认时间', 
    terms_ip VARCHAR(64) COMMENT '条款确认 IP（留证）', 
    staff_id BIGINT COMMENT '负责店员', 
    checkin_at DATETIME COMMENT '实际入住时间', 
    checkout_at DATETIME COMMENT '实际离店时间', 
    checkin_note VARCHAR(255) COMMENT '入住健康初检记录', 
    checkout_note VARCHAR(255) COMMENT '退房物品清点与消杀记录', 
    terminate_reason VARCHAR(255) COMMENT '异常终止原因（必填于终止类）', 
    cancel_reason VARCHAR(255) COMMENT '取消 / 爽约原因', 
    extend_times INTEGER NOT NULL COMMENT '延期次数', 
    idempotent_key VARCHAR(64) COMMENT '幂等键', 
    remark TEXT COMMENT '备注', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (idempotent_key), 
    UNIQUE (order_no)
);

CREATE INDEX idx_board_date_status ON boarding_order (check_in_date, check_out_date, status);

CREATE INDEX idx_board_room_status ON boarding_order (room_id, status);

CREATE INDEX ix_boarding_order_pet_id ON boarding_order (pet_id);

CREATE INDEX ix_boarding_order_room_id ON boarding_order (room_id);

CREATE INDEX ix_boarding_order_staff_id ON boarding_order (staff_id);

CREATE INDEX ix_boarding_order_status ON boarding_order (status);

CREATE INDEX ix_boarding_order_user_id ON boarding_order (user_id);

CREATE TABLE boarding_pickup_task (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_id BIGINT NOT NULL COMMENT '寄养订单 ID', 
    task_type VARCHAR(16) NOT NULL COMMENT 'pickup 上门接 / return 送宠到家', 
    status VARCHAR(16) NOT NULL COMMENT '任务状态', 
    address VARCHAR(255) COMMENT '接送地址', 
    slot_time VARCHAR(32) COMMENT '约定时间段', 
    staff_id BIGINT COMMENT '指派店员', 
    fee_cents INTEGER NOT NULL COMMENT '费用（分）', 
    departed_at DATETIME COMMENT '出发时间', 
    picked_at DATETIME COMMENT '接到时间', 
    arrived_at DATETIME COMMENT '送达时间', 
    sign_off_by VARCHAR(50) COMMENT '宠主签收人', 
    remark VARCHAR(255) COMMENT '备注', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_boarding_pickup_task_order_id ON boarding_pickup_task (order_id);

CREATE INDEX ix_boarding_pickup_task_status ON boarding_pickup_task (status);

CREATE TABLE boarding_room (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    room_no VARCHAR(32) NOT NULL COMMENT '房号', 
    room_type VARCHAR(20) NOT NULL COMMENT 'standard 标准单间 / garden 花园景房 / sunny 阳光房 / vip 套房', 
    name VARCHAR(50) NOT NULL COMMENT '房型展示名', 
    species_limit VARCHAR(10) NOT NULL COMMENT '适配物种 dog / cat / all', 
    weight_limit INTEGER COMMENT '最大适配体重（kg）', 
    ratio_percent INTEGER NOT NULL COMMENT '房型系数百分比：100=1.0 倍，120=1.2 倍', 
    capacity INTEGER NOT NULL COMMENT '可容纳宠物数（未绝育 / 攻击倾向强制 1）', 
    status VARCHAR(16) NOT NULL COMMENT 'idle 空闲 / occupied 占用中 / cleaning 清洁中 / maintenance 维护中', 
    facilities VARCHAR(255) COMMENT '设施标签，逗号分隔', 
    remark VARCHAR(255) COMMENT '备注', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (room_no)
);

CREATE INDEX ix_boarding_room_room_type ON boarding_room (room_type);

CREATE INDEX ix_boarding_room_status ON boarding_room (status);

UPDATE alembic_version SET version_num='4f280147a257' WHERE alembic_version.version_num = '916b67aae47e';

-- Running upgrade 4f280147a257 -> df7c24fc45f6

CREATE TABLE camera_device (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    room_id BIGINT NOT NULL COMMENT '绑定的宠舍 ID', 
    name VARCHAR(60) NOT NULL COMMENT '设备名，如 花园景房 B201 摄像头', 
    provider_type VARCHAR(20) NOT NULL COMMENT 'local_webcam 门店电脑采集 / rtsp_hls 网络摄像头（预留）/ cloud_live 云直播（预留）', 
    stream_url VARCHAR(255) COMMENT '正式版 RTSP/HLS 地址（预留）', 
    status VARCHAR(12) NOT NULL COMMENT 'online / offline / disabled', 
    enabled SMALLINT NOT NULL COMMENT '1 启用', 
    fps INTEGER NOT NULL COMMENT '采集帧率', 
    resolution VARCHAR(20) NOT NULL COMMENT '分辨率', 
    last_heartbeat_at DATETIME COMMENT '最近心跳时间', 
    remark VARCHAR(255) COMMENT '备注', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_camera_device_room_id ON camera_device (room_id);

CREATE INDEX ix_camera_device_status ON camera_device (status);

CREATE TABLE camera_session (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_id BIGINT NOT NULL COMMENT '寄养订单 ID', 
    user_id BIGINT NOT NULL COMMENT '观看人（宠主）', 
    device_id BIGINT NOT NULL COMMENT '设备 ID', 
    token VARCHAR(64) NOT NULL COMMENT '短期观看凭证', 
    token_expires_at DATETIME NOT NULL COMMENT '凭证过期时间', 
    started_at DATETIME COMMENT '开始观看时间', 
    ended_at DATETIME COMMENT '结束时间', 
    duration_seconds INTEGER NOT NULL COMMENT '观看时长（秒）', 
    frames INTEGER NOT NULL COMMENT '已转发帧数', 
    ip VARCHAR(64) COMMENT '来源 IP（留痕）', 
    user_agent VARCHAR(255) COMMENT 'UA 摘要（留痕）', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (token)
);

CREATE INDEX ix_camera_session_order_id ON camera_session (order_id);

CREATE INDEX ix_camera_session_user_id ON camera_session (user_id);

CREATE TABLE camera_snapshot (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_id BIGINT NOT NULL COMMENT '寄养订单 ID', 
    user_id BIGINT NOT NULL COMMENT '抓拍人', 
    device_id BIGINT COMMENT '设备 ID', 
    image_url VARCHAR(255) NOT NULL COMMENT '图片地址', 
    note TEXT COMMENT '备注', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_camera_snapshot_order_id ON camera_snapshot (order_id);

CREATE INDEX ix_camera_snapshot_user_id ON camera_snapshot (user_id);

CREATE TABLE cart_item (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    user_id BIGINT NOT NULL COMMENT '宠主 ID', 
    sku_id BIGINT NOT NULL COMMENT 'SKU ID', 
    quantity INTEGER NOT NULL COMMENT '数量', 
    pet_id BIGINT COMMENT '关联宠物（用于过敏校验）', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX idx_cart_user_sku_pet ON cart_item (user_id, sku_id, pet_id);

CREATE INDEX ix_cart_item_sku_id ON cart_item (sku_id);

CREATE INDEX ix_cart_item_user_id ON cart_item (user_id);

CREATE TABLE goods_order (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_no VARCHAR(32) NOT NULL COMMENT '用品单号', 
    user_id BIGINT NOT NULL COMMENT '宠主 ID', 
    status VARCHAR(24) NOT NULL COMMENT '订单状态', 
    pay_status VARCHAR(20) NOT NULL COMMENT 'unpaid / paid_offline / refunded_offline', 
    item_count INTEGER NOT NULL COMMENT '商品件数（连带率用）', 
    total_cents INTEGER NOT NULL COMMENT '应付总额（分）', 
    delivery_fee_cents INTEGER NOT NULL COMMENT '配送费（分）', 
    pickup_method VARCHAR(16) NOT NULL COMMENT 'self / delivery', 
    address VARCHAR(255) COMMENT '配送地址', 
    remark VARCHAR(255) COMMENT '备注', 
    pickup_code VARCHAR(12) NOT NULL COMMENT '核销码（8 位大写字母+数字，店员输入/扫码）', 
    idempotent_key VARCHAR(64) COMMENT '幂等键（与核销码分离：前者防重复提交，后者给店员核销）', 
    pet_id BIGINT COMMENT '下单时关联宠物（过敏校验留痕）', 
    stock_released SMALLINT NOT NULL COMMENT '库存是否已回补：1 是（防重复回补）', 
    cancel_reason VARCHAR(255) COMMENT '取消 / 缺货原因', 
    confirmed_at DATETIME COMMENT '确认时间', 
    completed_at DATETIME COMMENT '完成（核销）时间', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id), 
    UNIQUE (idempotent_key), 
    UNIQUE (order_no)
);

CREATE INDEX ix_goods_order_pickup_code ON goods_order (pickup_code);

CREATE INDEX ix_goods_order_status ON goods_order (status);

CREATE INDEX ix_goods_order_user_id ON goods_order (user_id);

CREATE TABLE goods_order_item (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    order_id BIGINT NOT NULL COMMENT '订单 ID', 
    sku_id BIGINT NOT NULL COMMENT 'SKU ID', 
    product_id BIGINT NOT NULL COMMENT 'SPU ID', 
    product_name VARCHAR(120) NOT NULL COMMENT '商品名快照', 
    spec_name VARCHAR(80) NOT NULL COMMENT '规格快照', 
    image VARCHAR(255) COMMENT '主图快照', 
    price_cents INTEGER NOT NULL COMMENT '成交单价（分）', 
    quantity INTEGER NOT NULL COMMENT '数量', 
    subtotal_cents INTEGER NOT NULL COMMENT '小计（分）', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_goods_order_item_order_id ON goods_order_item (order_id);

CREATE TABLE product (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    name VARCHAR(120) NOT NULL COMMENT '商品名', 
    brand VARCHAR(60) COMMENT '品牌', 
    category VARCHAR(20) NOT NULL COMMENT 'basic_food 主粮 / snack 零食 / toy 玩具 / clean 清洁 / clothes 服饰 / health 保健 / daily 日用', 
    species VARCHAR(10) NOT NULL COMMENT 'dog / cat / all', 
    stage VARCHAR(10) NOT NULL COMMENT 'puppy / adult / senior / all', 
    size VARCHAR(10) NOT NULL COMMENT 'small / medium / large / all', 
    main_image VARCHAR(255) COMMENT '主图地址', 
    detail TEXT COMMENT '详情（富文本/纯文本）', 
    selling_points VARCHAR(255) COMMENT '卖点标签，逗号分隔', 
    promo_tags VARCHAR(120) COMMENT '促销标签，逗号分隔', 
    allergy_tags VARCHAR(255) COMMENT '过敏原标签，逗号分隔（如：燕麦,鸡肉,香精）', 
    taboo_tags VARCHAR(255) COMMENT '禁忌标签，逗号分隔（如：幼犬不宜,肾病禁用,怀孕期慎用）', 
    min_weight INTEGER COMMENT '适用体重下限（kg）', 
    max_weight INTEGER COMMENT '适用体重上限（kg）', 
    status VARCHAR(10) NOT NULL COMMENT 'on / off', 
    sort_no INTEGER NOT NULL COMMENT '排序权重（越小越靠前）', 
    sales_count INTEGER NOT NULL COMMENT '累计销量（门店自营口径）', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_product_category ON product (category);

CREATE INDEX ix_product_status ON product (status);

CREATE TABLE product_sku (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    product_id BIGINT NOT NULL COMMENT 'SPU ID', 
    spec_name VARCHAR(80) NOT NULL COMMENT '规格名，如 2kg / 鸡肉味', 
    price_cents INTEGER NOT NULL COMMENT '售价（分）', 
    weight_g INTEGER COMMENT '规格重量（克），用于自动算单位价', 
    unit_price_cents INTEGER COMMENT '单位价（分/kg），比价用', 
    stock INTEGER NOT NULL COMMENT '库存（件）', 
    warn_threshold INTEGER NOT NULL COMMENT '库存预警阈值', 
    barcode VARCHAR(64) COMMENT 'SKU 条码（扫码核销用）', 
    enabled SMALLINT NOT NULL COMMENT '1 上架', 
    created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT (now()), 
    updated_at DATETIME NOT NULL COMMENT '更新时间' DEFAULT (now()), 
    PRIMARY KEY (id)
);

CREATE INDEX ix_product_sku_product_id ON product_sku (product_id);

UPDATE alembic_version SET version_num='df7c24fc45f6' WHERE alembic_version.version_num = '4f280147a257';

-- Running upgrade df7c24fc45f6 -> 21fa05283681

ALTER TABLE boarding_order ADD COLUMN dropoff_method VARCHAR(16) NOT NULL COMMENT '送宠到店：self 自行送到 / pickup 上门接宠';

ALTER TABLE boarding_order ADD COLUMN pickup_back_method VARCHAR(16) NOT NULL COMMENT '离店接宠：self 自行接取 / return 送宠到家';

ALTER TABLE boarding_order MODIFY shipping_method VARCHAR(16) NOT NULL COMMENT '历史字段（兼容旧数据）：self 自送 / pickup 上门接 / return 送宠到家';

UPDATE boarding_order SET dropoff_method = 'pickup' WHERE shipping_method = 'pickup';

UPDATE boarding_order SET pickup_back_method = 'return' WHERE shipping_method = 'return';

UPDATE alembic_version SET version_num='21fa05283681' WHERE alembic_version.version_num = 'df7c24fc45f6';

