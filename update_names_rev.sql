select *, ROWID
from items i
WHERE	i.name like 'ambassador%'

select i.name, h.id, count(0) as 'cnt'
FROM	hist h
join    items i
on (h.id=i.rowid and i.name like 'ambassador%')
group by i.name, h.id
/*
Ambassador Barrel				3104	51
Ambassador Barrel Blueprint		2946	208
Ambassador Receiver				3105	57
Ambassador Receiver Blueprint	2947	201
Ambassador Stock				3106	50
Ambassador Stock Blueprint		2948	204
*/
update hist
set id=3106
where id=2948
and not exists (
	select 1
	from hist h_
	where h_.ts=hist.ts
	and   h_.id=3106
)

delete from hist
where hist.id in (2946, 2947, 2948)

delete from items
where ROWID in (2946, 2947, 2948)

delete from items_attrs
where item_id in (2946, 2947, 2948)