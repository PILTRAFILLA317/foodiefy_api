-- A known upper bound never fabricates a lower bound.
alter table public.shopping_items drop constraint shopping_items_check;
alter table public.shopping_items add constraint shopping_items_range_check check (
 quantity_max is null or (quantity_max>0 and quantity_max<1e12 and (quantity is null or quantity_max>=quantity))
);
