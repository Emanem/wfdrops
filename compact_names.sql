-- select the names
-- and pick the latest
-- hopefully those are properly spelled
CREATE TEMPORARY TABLE target_name(tgt_name TEXT, tgt_id INTEGER)

insert into temp.target_name
select i.name, i.ROWID
FROM	items i
join    (
	select max(i.rowid) as id, count(0) as cnt
	FROM items i  
	where 1=1
	group by lower(i.name)
	having count(0) > 1
) ids
on (i.ROWID=ids.id)

--select * from temp.target_name

CREATE TEMPORARY TABLE idsrc_idtarget(src_id INTEGER, tgt_id INTEGER)

insert into temp.idsrc_idtarget
select i.ROWID, t.tgt_id
FROM	items i
JOIN	temp.target_name t
on (lower(t.tgt_name) = lower(i.name) and i.ROWID != t.tgt_id)

--select * from temp.idsrc_idtarget
--
CREATE TEMPORARY TABLE idsrc_to_convert(src_id INTEGER, ts TIMESTAMP, tgt_id INTEGER)

insert into idsrc_to_convert
select h.id, h.ts, i.tgt_id
FROM	hist h
join	idsrc_idtarget i
on (i.src_id = h.id)

-- remove the rows which are already existing
delete from idsrc_to_convert
WHERE	1=1
AND		exists (
	select 1
	FROM	hist h
	WHERE	1=1
	AND		h.id=idsrc_to_convert.tgt_id
	AND		h.ts=idsrc_to_convert.ts
)

-- this should always be 0
select *
FROM	hist h
join  idsrc_to_convert i
on (h.id=i.tgt_id and h.ts=i.ts)

-- finally update hist
update hist
set id = (
	select  r.tgt_id
	FROM	temp.idsrc_to_convert r
	WHERE	r.src_id=hist.id
	AND		r.ts=hist.ts
)
WHERE exists (
	select  1
	from   temp.idsrc_to_convert r
	where 1=1
	and		r.src_id=hist.id
	AND		r.ts=hist.ts
)

--- this should always be 0 
select *
FROM	hist h
join  idsrc_to_convert i
on (h.id=i.src_id and h.ts=i.ts)

-- remove old names
DELETE from items
where 1=1
AND		exists (
	select 1
	FROM idsrc_idtarget i
	where  i.src_id=items.ROWID
)

-- remove old attributes
DELETE from items_attrs
where 1=1
AND		exists (
	select 1
	FROM idsrc_idtarget i
	where  i.src_id=items_attrs.item_id
)

-- finally check we have no duplicate names or data
select	n.n, h.ts
FROM	hist h
JOIN	(
	SELECT  lower(n.name) as n, n.ROWID as id
	FROM	items n
) n
on (h.id=n.id)
group by n.n, h.ts
having count(0) > 1

-- ensure we don't have 'dangling' data 
select *
FROM	hist h
LEFT JOIN	items i
on (h.id=i.ROWID)
WHERE	1=1
AND		i.name is NULL

-- delete dangling data 
delete from hist
where 1=1
AND	not exists (
	select 1
	from items i
	WHERE	1=1
	AND		hist.id=i.ROWID
)
