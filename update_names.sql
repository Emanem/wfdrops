CREATE TEMPORARY TABLE name_replace(tgt_name TEXT, tgt_id INTEGER, src_name TEXT, src_id INTEGER)

insert into temp.name_replace
select 	i.name as 'tgt_name', i.ROWID as 'tgt_id',
		j.name as 'src_name', j.ROWID as 'src_id'
FROM	items i
JOIN	items j
on (i.name=(j.name || ' Blueprint'))
WHERE	1=1
--AND		i.name like 'octavia%'

CREATE TEMPORARY TABLE ts_remove(src_ts TIMESTAMP, src_id INTEGER, tgt_ts TIMESTAMP, tgt_id TIMESTAMP)

insert into temp.ts_remove
select	h.ts as 'src_ts', h.id as 'src_id',
		NULL, r.tgt_id
FROM	temp.name_replace r
JOIN	hist h
on (r.src_id=h.id)

update temp.ts_remove
set tgt_ts=(
	select h.ts
	FROM	hist h
	WHERE	h.ts=src_ts
	AND		h.id=tgt_id
)

select h.*
FROM	hist h
join	temp.ts_remove r
on (h.ts=r.tgt_ts and (h.id=r.tgt_id or h.id=r.src_id))

delete from hist 
where ROWID in (
	select h.ROWID
	FROM	hist h
	join	temp.ts_remove r
	on (h.ts=r.tgt_ts and h.id=r.src_id and r.tgt_ts is not NULL)
)

update hist
SET		id = (
	select  r.tgt_id
	FROM	temp.name_replace r
	WHERE	r.src_id=hist.id
)
WHERE	id in (
	select  r.src_id
	FROM	temp.name_replace r
)

select 	h.id, h.ts, count(0) as 'cnt'
FROM	hist h
WHERE	1=1
group by h.id, h.ts
having count(0) > 1

delete from items
where name in (
	select 	src_name
	FROM	temp.name_replace
)

CREATE TABLE IF NOT EXISTS _hist(id integer, ts timestamp, volume integer, min integer, max integer, open integer, close integer, avg real, w_avg real, median real, m_avg real)

CREATE INDEX IF NOT EXISTS i1 ON _hist(id)

insert into _hist
select * from hist

drop table hist

CREATE TABLE IF NOT EXISTS hist(id integer, ts timestamp, volume integer, min integer, max integer, open integer, close integer, avg real, w_avg real, median real, m_avg real)

CREATE INDEX IF NOT EXISTS i1 ON hist(id)

insert into hist
select * from _hist

drop table _hist

select * from temp.ts_remove
select * from temp.name_replace