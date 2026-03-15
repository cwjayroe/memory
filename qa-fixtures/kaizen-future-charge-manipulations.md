## 

## Areas of work {#areas-of-work}

[Areas of work](#areas-of-work)

[Charge creation RQ job](#charge-creation-rq-job)

[Plans](#plans)

[SCI checkout](#sci-checkout)

[New subscription creation & purchase items database](#new-subscription-creation-&-purchase-items-database)

[Existing subscription updates & purchase items GETs](#existing-subscription-updates-&-purchase-items-gets)

[Cancelling a subscription](#cancelling-a-subscription)

[Charge date updates](#charge-date-updates)

[Charge creation](#charge-creation)

[Regen](#regen)

[Bundle selection endpoint](#bundle-selection-endpoint)

[Charge processing](#charge-processing)

[Error charge processing](#error-charge-processing)

[Prepaids](#prepaids)

[Customer portal](#customer-portal)

[Merchant portal](#merchant-portal)

[Future skipped charges](#future-skipped-charges)

[Discounts](#discounts)

[Flows](#flows)

[Contract sync](#contract-sync)

[Open questions](#open-questions)

Gated behind betaflag - `enable_multiple_active_queued_charges`  
Example customer that has 4 active queued charges - [https://wills-nice-gifs-sp.admin.stage.rechargeapps.com/merchant/customers/117734646](https://wills-nice-gifs-sp.admin.stage.rechargeapps.com/merchant/customers/117734646)

**NOTE: Unless explicitly stated, all of this work should be behind the new betaflag**

### Charge creation RQ job {#charge-creation-rq-job}

We need to create a new RQ job that runs daily and creates queued charges as necessary for these purchase items. When evaluating the number of charges a purchase\_item has, we only look at QUEUED charges.

**Old approach** 

- Charge processes successfully → new charge created

**New approach**

- Charge processes successfully → charge does not have multiple queued charges → new charge created

#### Job Frequency

Daily

#### DB update ideas

There are 779m records in the purchase item table and 42m records in the metafield table.

1. Create new columns for all 4 settings in the purchase item table and plans table  
2. Use the metafields table  
3. Create a single new column in the plans table and purchase item table that is JSON  
   1. Store all of our settings in those columns

#### DB queries

1. Select store.id where for all stores that have the new GA enabled  
2. Select all purchase items that have a `max_queued_charge` value set and a charge\_creation\_day\_of\_week/charge\_creation\_day\_of\_month value set  
   1. Filter down to only purchase items with a value for charge\_creation\_day\_of\_week that is equal to todays day of week OR charge\_creation\_day\_of\_month equal to the day of month  
   2. **We'll want to think through how to make this query performant as more stores adopt this feature**  
      1. Short term  
         1. We can start with GAs to prove this out and discuss indexes + columns   
      2. Long term  
         1. New column with JSON and indexes on it?  
         2. New columns for all the things… and indexes on those things?  
3. Get all queued charges for a purchase item

 

#### General Walkthrough

- Get the ids of stores that have the GA enabled  
- For those stores, load all purchase items that have a max\_queued\_charge > 1 value & charge\_creation\_day\_of\_week/charge\_creation\_day\_of\_month is set that matches the runtimes day of week or day of month  
- For each purchase items found, get its QUEUED charges  
  - Only look for QUEUED charges that are today or in the future   
- If the count of queued charges on the purchase\_item < max\_queued\_charge value, create the number of missing charges  
  - When creating the new charges, we should base their line items for the bundles off the last processed charge  
  - Create the next queued charge date based on the latest queued charge for the purchase item

#### Work to do

- [RQJob] Build new RQ job for charge creation  
  -  As a merchant, i want to have my multiple queued changes created on specific days of the week, or days of the month,  so that i can accurately setup my meal kit plans  
  - We need to create a new RQ job that detects when a new queued charge should be created and creates it for the merchant.  
  - This can be split into multiple tickets if we get to it and it feels like its more than 1 tickets worth of work  
  - The RQ job should do the following  
    - Query for all stores where they have the GA `enable_multiple_queued_charges` set  
    - Get all purchase items for those stores where the following conditions are met  
      - The purchase\_item has max\_queued\_charges > 1  
      - The purchase\_item has a charge\_creation\_day\_of\_month that is the same date as the day of month the job is running OR charge\_creation\_day\_of\_week is the same day of week as the day of week the job is running  
      - The purchase\_item has a count of QUEUED charges < max\_queued charge value  
    - Create the next upcoming charge with the following  
      - The charge date should be the purchase\_items latest queued charge `original_charge_charge` + the interval from the purchase\_item  
      - The charge line items should be the same as the purchase\_items most recently processed charges items

#### Example

**Setup**  
Purchase item

- id : 1  
- charge\_creation\_day\_of\_week: Wednesday  
- Max\_queued\_charges: 4

Charges

1. Charge 1 - charge\_date - March 8th - Sunday  
   1. Original\_charge\_date - March 4th  
2. Charge 2 - charge\_date - March 15th - Sunday  
   1. Original\_charge\_date - March 11th  
3. Charge 3 - charge\_date - March 22nd - Sunday  
   1. Original\_charge\_date - March 18th  
4. Charge 4 - charge\_date - March 29th - Sunday  
   1. Original\_charge\_date - March 25th

**Walkthrough**

- Charge #1 processes on Sunday  
  - No new charge is created from this charge processing  
- RQ job runs on Monday & Tuesday, nothing happens  
- RQ job runs on Wednesday (my dude)   
- Pulls all purchase items that have a charge\_creation\_day\_of\_week on Wednesday  
  - Returns purchase\_item id 1  
- Pulls all queued charges for that purchase item  
  - select * from charge purchase\_item join charge on charge.id = charge\_purchase\_item.charge\_id where store\_id = … and purchase\_item\_id = 1 and charge.status = QUEUED  
- Determines that there are only 3 queued charges for the purchase item  
- Looks at the latest queued charge for the purchase item and pulls the `original_charge_date` from the charges general attributes  
  - Original\_charge\_date is March 25th - wednesday  
- Creates a new charge for April 1st

### Plans {#plans}

`Charge_creation_day_of_week` or `charge_creation_day_of_month` is required if you are setting `max_queued_charges`.

#### charge\_modification\_restriction\_window [not required]

This is a new column that needs to be added to the `plan` table. It sets how many days before a charge's `charge_date` that it **can not** be modified. This is a nice to have, but not strictly required for release.

When merchants set this, it will block customers from being able to modify the charges charge\_date once its within the cutoff window. For example, if there is a charge that processes on the 5th and the plan has a cutoff window of 2 days, on the 3rd, the customer will no longer be able to make changes to that charge date.

Column info

* Type = int  
* Default = 0  
* Nullable = false

#### max\_queued\_charges

This is a new column that needs to be added to the `plan` table. It sets how many future queued charges should be generated when a charge is created from this plan.

When creating/updating plans, we need to support the ability to set and update a new value, `max_queued_charges`. This needs to be supported in the merchant portal and in the API.

We won't support a max\_queued\_charges value > 1 if the plan is prepaid.  
The upper limit on max\_queued\_charges is 6

Column Info

* Type = int  
* Default = 1  
* Nullable = false

#### charge\_creation\_day\_of\_week

Allows the merchant to control on what day of week their upcoming charges are created.

Mutually exclusive with charge\_creation\_day\_of\_month. This is also connected to the plan interval, this can only be used when the interval is `weekly`.

This can only have values of Monday/Tuesday/Wednesday(mydudes)/Thursday/Friday/Saturday/Sunday

Column info

* Type = varchar(50)  
* Default = None  
* Nullable = true

#### charge\_creation\_day\_of\_month

Allows the merchant to control on what day of the month their upcoming charges are created.

Mutually exclusive with charge\_creation\_day\_of\_week. This is also connected to the plan interval, this can only be used when the interval is `monthly`

This can only have values of 1-31.

- This is really 1 - end of month  
- Interesting nuance to handle when the value is 31 and the month only has 28 days  
- If charge\_creation\_day\_of\_month = 31  
  - February - charge creation on 2/28  
  - March - charge creation on 3/31

Column info

* Type = int  
* Default = None  
* Nullable = True

#### Work to do

- [api] POST /plans should accept new values  
  - Merchant need to be able to set our new values through the API to enable the merchant portal and direct API calls  
  - Constraints  
    - Charge\_creation\_day\_of\_week - is only able to be set if the plan type is weekly  
    - Charge\_creation\_day\_of\_month -  is only able to be set if the plan type is monthly  
    - Charge\_creation\_day\_of\_week & Charge\_creation\_day\_of\_month are only able to be set if max\_queued\_charges is provided  
    - You can not ever set both Charge\_creation\_day\_of\_week & Charge\_creation\_day\_of\_month  
    - Block creating a prepaid plan with a max\_queued\_charges set  
  - New settings  
    - Max\_queued\_charges  
    - Charge\_creation\_day\_of\_week  
    - Charge\_creation\_day\_of\_month  
    - Modification\_cut\_off\_window - not strictly required for this project  
- [api] PUT /plans should accept new values  
  - Merchant need to be able to set our new values through the API to enable the merchant portal and direct API calls  
  - Constraints  
    - Block updating a plan thats a prepaid to have a max\_queued\_charges set  
    - Block updating a has a max\_queued\_charges set to be a prepaid  
    - Block updating a to have a Charge\_creation\_day\_of\_week & Charge\_creation\_day\_of\_month set  
      - You have to pick 1 or the other  
  - New settings  
    - Max\_queued\_charges  
    - Charge\_creation\_day\_of\_week  
    - Charge\_creation\_day\_of\_month  
    - Modification\_cut\_off\_window - not strictly required for this project  
- [api] GET /plans should return new values  
  - When calling the /plans API, we should return these new values in the API response  
    - Max\_queued\_charges  
    - Charge\_creation\_day\_of\_week  
    - Charge\_creation\_day\_of\_month  
    - Modification\_cut\_off\_window - not strictly required for this project  
- [api] GET /plans/:id should return new values  
  - When calling the /plans API, we should return these new values in the API response  
    - Max\_queued\_charges  
    - Charge\_creation\_day\_of\_week  
    - Charge\_creation\_day\_of\_month  
    - Modification\_cut\_off\_window - not strictly required for this project  
- [db] Create new columns for the plans table  
  - We need to create the new columns in the database to support storing our new plan settings  
    - We need to give some thought to how we are going to create these  
      - 4 new columns?  
      - 1 column with JSON keys?  
      - Indexes  
    - In the short-term, we should use the `add_ons` column with property mappings on the model to prove out this work  
  - Max\_queued\_charges  
    - Int   
    - Default 0  
    - Not nullable  
  - Charge\_creation\_day\_of\_week  
    - varchar(50)  
    - Default none  
    - nullable  
  - Charge\_creation\_day\_of\_month  
    - Int   
    - Default none  
    - nullable  
  - Modification\_cut\_off\_window  
    - Int   
    - Default 0  
    - Not nullable

---

### SCI checkout {#sci-checkout}

When a customer checks out with a bundle and plan that has a max\_queued\_charges > 1, we should create the number of queued charges set on the plan.

#### Finding the correct plan

For bundle items in checkout, we need to find the matching plan to determine if we should create multiple queued charges (need to look at max\_queued\_charges). 

##### Find plan by external\_product\_id & frequency

We can use `PlanService().get_plan_for_external_product_and_frequencies,` but this has proved error-prone at times. Merchants are able to create multiple plans for the same product with the same frequency.

We will retrieve the relevant plan directly in the subscription controller based off subscription details. This will avoid changing how all bundle subscriptions are imported in SCI checkout which has big unknowns and carries risk. We can then account for edge cases where multiple plans match by product/frequency (detailed below) which will apply to all subscription CRUD operations, not just SCI checkout.

#### Real world scenarios where a external product id has multiple plans with the same frequency

- Split plans between checkout & customer portal where checkout gets a discount  
  - Dynamic pricing is checkout only - Merchants create a cloned plan that is a standard subscription for the customer portal  
- Prepaid v2 - External\_variant\_ids are different for each but frequencies and product\_id are the same  
  - No prepaid support in this project  
- Variant restrictions  
  - Creating cloned plans with different discounts that target different variants

#### Work to do

- [BE] Find the plan for the bundle selection  
  - In SCI checkout, when creating purchase items, if the recharge\_plan\_id is not provided in the bulk\_subscriptions\_data, we need to go find a matching plan id  
  - Do a search similar to what is being done here (code)  
  - We are not going to try to update the fallback plan search in SCI checkout  
    - This would be risky and has far reaching impact  
- [BE] Update purchase item creation if the If the plan has a max\_queued\_charges > 1  
  - After finding the plan, we need to evaluate the max\_queued\_charges on the plan to determine if there are multiple charges that need to be created  
  - If the plan has a max\_queued\_charges > 1, we need to do the following things  
    - Create # of queued charges from max\_queued\_charges  
    - Create # of bundle selections and bundle selection items

#### Scenarios

- Single bundle with max queued charge > 1 cart  
- If there are multiple bundles with different max\_queued\_charge values  
- If there is a onetime mixed cart (onetime + bundle with max queued charge > 1)  
- If there is a regular subscription mixed cart (1month non-bundle subscription + bundle with max queued charge > 1)  
- Think through a flows scenario

---

### New subscription creation & purchase items database {#new-subscription-creation-&-purchase-items-database}

#### Database updates

##### charge\_modification\_restriction\_window [not required]

This is a new column that needs to be added to the `purchase_item` table. It sets how many days before a charge's `charge_date` that it **can not** be modified. This is a nice to have, but not strictly required for release.

When merchants set this, it will block customers from being able to modify the charges charge\_date once its within the cutoff window. For example, if there is a charge that processes on the 5th and the plan has a cutoff window of 2 days, on the 3rd, the customer will no longer be able to make changes to that charge date.

Column info

* Type = int  
* Default = 0  
* Nullable = false

##### max\_queued\_charges

This is a new column that needs to be added to the `purchase_item` table. It sets how many future queued charges should be generated when a charge is created from the purchase\_item.

When creating/updating `purchase_item`, we need to support the ability to set and update a new value, `max_queued_charges`. This needs to be supported in the merchant portal and in the API.

We won't support a max\_queued\_charges value > 1 if the purchase\_item is prepaid.  
The upper limit on max\_queued\_charges is 6

Column Info

* Type = int  
* Default = 1  
* Nullable = false

##### charge\_creation\_day\_of\_week

Allows the merchant to control on what day of week their upcoming charges are created.

Mutually exclusive with charge\_creation\_day\_of\_month. This is also connected to the purchase\_item interval, this can only be used when the interval is `weekly`.

This can only have values of Monday/Tuesday/Wednesday(mydudes)/Thursday/Friday/Saturday/Sunday

Column info

* Type = varchar(50)  
* Default = None  
* Nullable = true

##### charge\_creation\_day\_of\_month

Allows the merchant to control on what day of the month their upcoming charges are created.

Mutually exclusive with charge\_creation\_day\_of\_week. This is also connected to the purchase\_item interval, this can only be used when the interval is `monthly`

This can only have values of 1-31.

- This is really 1 - end of month  
- Interesting nuance to handle when the value is 31 and the month only has 28 days  
- If charge\_creation\_day\_of\_month = 31  
  - February - charge creation on 2/28  
  - March - charge creation on 3/31

Column info

* Type = int  
* Default = None  
* Nullable = True

#### Purchase item creation

When a customer/merchant creates a new bundle via the API or merchant portal, if that bundle plan has a max\_queued\_charges setting, we need to create the number of charges specified by the max\_queued\_charges setting.

When creating the purchase\_item, we should take the all of the 4 new columns on the plan and store the in general attributes on the purchase\_item table

When creating a purchase item that has multiple queued charges, we should create a bundle selection (and bundle selection items) for each queued charge we create. 

#### Work to do

- [BE] When creating a purchase\_item that has multiple queued charges, we need to create multiple bundle selections  
  - When we create a purchase\_item, if it has bundle selections, we create a bundle selection and bundle selection items for it. We need to extend this to support creating a bundle selection (and items) per new charge we've created  
- [BE] When creating a new subscription and provided a specific plan id, we should save the new plan attributes onto the purchase\_item table  
  - When an API caller passes the `plan_id` in the POST to purchases\_items, we should lookup the plan and save our new values to the purchase\_item GAs  
    - Max\_queued\_charges  
    - Charge\_creation\_day\_of\_week  
    - Charge\_creation\_day\_of\_month  
    - Modification\_cut\_off\_window  
- [DB] Create new columns for the purchase\_item table (if necessary)  
  - We need to support our new columns/GAs in the purchase\_item table.  
  - Max\_queued\_charges  
    - Int   
    - Default 0  
    - Not nullable  
  - Charge\_creation\_day\_of\_week  
    - varchar(50)  
    - Default none  
    - nullable  
  - Charge\_creation\_day\_of\_month  
    - Int   
    - Default none  
    - nullable  
  - Modification\_cut\_off\_window  
    - Int   
    - Default 0  
    - Not nullable  
- **[QUESTION]** If a call is not providing a specific plan id, should we allow API callers to set the new plan values on the purchase item directly from the API call? Or is this feature only accessible if you use plans?

#### Scenarios 

- Customer portal  
- Merchant portal  
- API

---

### Existing subscription updates & purchase items GETs {#existing-subscription-updates-&-purchase-items-gets}

**[QUESTION]** Do we want to allow updates to purchase items to include the new plan settings?

- For example: A merchant has a purchase\_item created with a `charge_creation_day_of_week` set to Tuesday, they shift their schedule and want to update the `charge_creation_day_of_week` for all customers to be on Wednesday   
- Yes

**[QUESTION]** When purchase items are updated today, they regen charge synchronously. Should these regens happen async? Do we care right now? 

- Probably easiest to not care for right now. If we start to see it as an issue, we can always come back and make it async later

**[QUESTION]** Can a purchase\_item have its max\_queued\_charge value updated?

- Yes, but not as necessary as charge\_creation\_day\_of\_week/charge\_creation\_day\_of\_month

#### General

When a customer updates existing subscriptions that have > 1 queued charge on them, we should update the queued charges appropriately. 

We should block *some* updates to purchase items that are going to cause trickle effects downstream. This is being done to help prevent many charges getting created/deleted/updated. The updates we know we want to block are

- Interval updates   
  - 1 week -> 2 weeks  
- Price updates

There are some purchase\_item updates we know we want to allow, specifically around our new columns/GAs we are adding to the purchase\_item table. We want to allow update for the following attributes

- Max\_queued\_charges  
- Charge\_creation\_day\_of\_week  
- Charge\_creation\_day\_of\_month  
- Modification\_cut\_off\_window

When returning responses from the purchase items endpoint, we need to be sure to include our new values we are adding

#### Price updates

When a merchant updates the price of a subscription that has multiple queued charges, that price change should trickle down to all the associated queued charges.

#### Interval updates

Merchants and customers should **not** be able to update purchase items or bundle selections, intervals. We will need to block this at the API to ensure it doesn't happen. We are doing this so that we can avoid having to delete and recreate a bunch of upcoming queued charges.

#### Work to do

- [BE] Prevent interval updates on purchase items if the purchase\_item has a max\_queued\_charges value set that is > 1  
- [api] GET /purchase\_items should return new values  
- [api] GET /purchase\_items/:id should return new values

#### Scenarios

These are specifically subscription-level updates, not charge-level updates

- A customer has 3 queued charges for a subscription  
  - They update the price of the subscription  
    - This change will apply to all queued charges for the purchase item  
  - They update the subscription's next charge date  
    - This will update the next queued charge for the purchase item

---

### Cancelling a subscription {#cancelling-a-subscription}

When a customer cancels a subscription that has multiple queued charges, all upcoming queued charges should be deleted. If there are multiple line items on an upcoming queued charge, the line item that was deleted should be removed, and the charges should still remain.

#### Work to do

- [API] Cancelling a subscription that has multiple queued charges, it should delete all queued charges for that purchase item  
- [QA] validate that if there is only 1 purchase item, the charges are all deleted  
- [QA] validate if there are multiple purchase items, charges are only deleted if they dont have line items from each purchase item on them

#### Scenarios

- Happy path - a customer has a single subscription that has 4 queued charges. If they cancel that subscription, we should delete all those queued charges  
- A customer has 2 subscriptions, 1 with max queued charges of 4 and another with no max queued charges. The subscription with max\_queued\_charges is cancelled.

---

### Charge date updates {#charge-date-updates}

If there are multiple queued charges for a subscription, the charge\_date of a charge cannot be updated outside of the subscription's cadence. 

If a customer has 4 queued charges spread out every 1 week, week 1s charge cannot be moved to the same date, or later, than week 2s charge.

#### Work to do

- [BE] If the charge being updated has other queued charges associated with its purchase item, we need to validate that its not being updated passed the max/min allowed by the purchase items frequency  
- [api] POST/PUT /api/charges/:id/change\_next\_charge\_date validates date on update  
- [api] POST /subscriptions/:id/set\_next\_charge\_date  
- [api] PUT /subscriptions/:id  

#### Example

Subscription

- Frequency - every 1 week  
- Max\_queued\_charges - 4

Charges

1. Charge 1 - charge\_date - March 1st  
   1. This charge charge\_date cannot be updated to be >= March 8th  
2. Charge 2 - charge\_date - March 8th  
   1. This charge charge\_date cannot be updated to be < March 8th or >= March 15th  
3. Charge 3 - charge\_date - March 15th  
   1. This charge charge\_date cannot be updated to be < March 15th or >= March 22nd  
4. Charge 4 - charge\_date - March 22nd  
   1. This charge charge\_date cannot be updated to be < March 22nd

---

### Charge creation {#charge-creation}

When a charge is created, we need to be sure the `charge_date` is stored in `original_charge_date` with the value of `charge_date`. This will allow us to track when the charge was originally scheduled for, even if the customer changes the charge date in the future.

#### Work to do

- [BE] Original\_charge\_date already exists on the charge general\_attribute, but it doesnt appear to get set in all situations  
- [BE] Update charges\_for\_items to create multiple charges if the purchase\_item dto has max\_queued\_charges  

---

### Regen {#regen}

When fetching bundle items for a regen, we need to look at the purchase item + the charge id that is being regen'd. This is because its possible that a customer the non-next queued charge to have different bundle contents on it. When we regen we cant rely on the purchase item to be 100% up-to-date with this content. 

#### Work to do

- [BE] Update regen to fetch bundle selection items for dynamic bundles from a combination of the charge id being regen'd and the purchase item  

#### Example

In this example, when charge 2 is regen'd we would need to look at the charge\_purchase\_items for the purchase item id + the charge id to determine the correct bundle selection to load bundle selection items from.

Setup

- Bundle selection - **ID** **1** - **Coffee bundle**  
  - Bundle selection item - **Dark roast coffee x2**  
  - Bundle selection item - **Light roast coffee x2**  
- Bundle selection - **ID** **2** - **Coffee bundle**  
  - Bundle selection item - **Dark roast coffee x2**  
  - Bundle selection item - **Light roast coffee x2**  
- Bundle selection - **ID** **3** - **Coffee bundle**  
  - Bundle selection item - **Dark roast coffee x2**  
  - Bundle selection item - **Light roast coffee x2**  
- Bundle selection - **ID** **4** - **Coffee bundle**  
  - Bundle selection item - **Dark roast coffee x2**  
  - Bundle selection item - **Light roast coffee x2**  

Action

- Customer updates Charge 2 to have **Medium roast coffee** instead of **Light roast coffee**  
- Outcome   
  - New bundle selection created - **ID 2 - Coffee bundle**  
    - Bundle selection item - **Dark roast coffee x2**  
    - Bundle selection item - **Medium roast coffee x2**  
- Recharge regens charge 2, we should pull the bundle details for bundle selection 2

Charges

1. Charge 1 - charge\_date - March 1st  
   1. Has bundle selection 1  
2. **Charge 2 - charge\_date - March 8th**  
   1. Has bundle selection 2  
   2. During regen, we need to select the bundle items for charge ID 2, its not enough to only look at the purchase item bundle selection   
3. Charge 3 - charge\_date - March 15th  
   1. Has bundle selection 3  
4. Charge 4 - charge\_date - March 22nd  
   1. Has bundle selection 4

---

### Bundle selection endpoint {#bundle-selection-endpoint}

The bundle selection endpoint will need to be updated to allow editing a specific charges bundle selection & bundle selection items instead of just updating the purchase items bundle selection. 

If a customer has 4 upcoming queued charges, this will allow customers to modify charge 2s bundle selection items without impacting charge 1, 3, or 4.

#### Work to do

- [API] Update the API to accept `charge_id`. If charge\_id is provided, we need to load details, and update, from the charge\_purchase\_items based on purchase\_item\_id + charge\_id

#### Example

Setup

- Bundle selection - **ID** **1** - **Coffee bundle**  
  - Bundle selection item - **Dark roast coffee x2**  
  - Bundle selection item - **Light roast coffee x2**  

Action

- Customer updates Charge 2 to have **Medium roast coffee** instead of **Light roast coffee**  
- Outcome   
  - New bundle selection created - **ID 2 - Coffee bundle**  
    - Bundle selection item - **Dark roast coffee x2**  
    - Bundle selection item - **Medium roast coffee x2**  

Charges

1. Charge 1 - charge\_date - March 1st  
   1. Has bundle selection 1  
2. **Charge 2 - charge\_date - March 8th**  
   1. Has bundle selection 2  
3. Charge 3 - charge\_date - March 15th  
4. Charge 4 - charge\_date - March 22nd

---

### Charge processing {#charge-processing}

After a charge processes, we will need to create another queued charge, but it needs to be after the last queued charge for the subscription. We can not create an upcoming charge based on the charge\_date of the charge that just processed; it needs to be based on the original\_charge\_date of the last queued charge for this subscription.

#### Work to do

- [BE] Update post charge processing webhook to not create a new upcoming charge if the charge purchase item has max\_queued\_charges & (charge\_creation\_day\_of\_week or charge\_creation\_day\_of\_month) set  

#### Example

Setup

- Today is March 1st & charge 1 just processed

Charges

1. Charge 1 - charged\_date - March 1st  
   1. No new charge gets created from this processing  
2. Charge 2 - March 8th  
3. Charge 3 - March 15th  
4. Charge 4 - March 22nd

---

### Error charge processing {#error-charge-processing}

**[NOTE]** We still need to discuss what this looks like in detail

If a charge errors, it does not get retried.

#### Work to do

- [BE] If a charge fails processing and its purchase item has max\_queued\_charges set, it should not be retried during error charge processing

#### Example

Setup

- Today is March 2nd

Charges

1. **Charge 1 - charged\_date - March 1st**  
   1. This charge fails to process on the 1st. It does not get retried on the 2nd  
2. Charge 2 - March 8th  
3. Charge 3 - March 15th  
4. Charge 4 - March 22nd

---

### Prepaids {#prepaids}

This project is not going to work on solving for prepaids. This is something that we will come back to in the future if product finds a demand for it.

#### Work to do 

- [api] POST /orders/:id/delay

---

### Customer portal {#customer-portal}

When customers take an action on a bundle through the customer portal, it is focuses on updating the entire bundle selection items and purchase item. We need to offer customers the ability to take action on a bundle that only impacts the single charge that they are looking at. If the customer has 4 queued charges and they modify the 2nd one, the other 3 charges should not be impacted.

The bundling widget in the customer portal needs to be updated to handle a customer only updating a single charges bundle selections/bundle selection items.

Today, the bundling widget on the customer portal is updating the purchase items bundle selection, it is not updating it only for the charge.

#### Work to do

- [Customer portal] Update the orders list page to show all upcoming queued charges  
- [Customer portal] Update to allow showing bundle selections for a specific charge  
- [Bundling widget] Update allow updating the bundle selection & bundle selection items for a specific charge  
- [Bundling widget] Update bundling widget to pull data based on a purchase\_item and charge\_id  
- [Customer portal] Update to block customers from being able to edit purchase item level data  
- [Customer portal] Block customers from skipping a future non-existing, queued charge if the purchase item has multiple queued charges  
- [Customer portal] Update the customer portal to not show some purchase\_item changes as available if max\_queued\_charges > 1  

---

### Merchant portal {#merchant-portal}

When merchants take an action on a bundle through the merchant portal it is focuses on updating the entire bundle selection items and purchase item. We need to offer the ability to edit the bundle selection/bundle selection items for a single, specific, charge. When editing this charge, it should not impact any of the other queued charges.

#### Work to do

- [Merchant portal] Update charge-level settings to allow editing bundle contents for a specific charge  
- [Merchant portal] Update the merchant portal to send the charge\_id in the `bundle_selections` api calls  
- [Merchant portal] Block merchants from skipping a future non-existing, queued charge  
- [Merchant portal] Update the merchant portal to not show some purchase\_item changes as available if max\_queued\_charges > 1  
- [Merchant portal] Update portal to allow new values on creation of a plan  
- [Merchant portal] Update portal to allow setting new values on updating a plan  

---

### Future skipped charges  {#future-skipped-charges}

We need to support skipping future charges to maintain compatibility with existing functionality that we have today. However, to reduce scope, we are going to block customers from skipping future charges that aren't created.

#### Work to do

- [BE] Prevent skipping a future non-existing, queued charge if the purchase item has multiple queued charges  

---

### Discounts {#discounts}

When discounts are applied, they apply to charges as they are regen'd depending on their eligibility at the time of regen. When a discount has application limits, such as the number of charges it can apply to per address, all future queued charges get it at time of regen (as long as they qualify). This could result in a behavior for multiple queued charges where originally all 4 charges show as having the discount, but after X amount of them process, the discount falls off. 

#### Work to do

- [QA] validate that a discount with a set number of charges for application does is correctly removed from upcoming charges

#### Example

Setup

- Discount  
- Duration = usage\_limit  
- Duration\_usage\_limit = 2

Charges

1. Charge 1 - charge\_date - March 1st  
   1. Discount initially applies  
2. Charge 2 - charge\_date - March 8th  
   1. Discount initially applies  
3. **Charge 3 - charge\_date - March 15th**  
   1. Discount initially applies  
   2. After charge #2 processes, this charge no longer qualifies so it loses the discount  
4. **Charge 4 - charge\_date - March 22nd**  
   1. Discount initially applies  
   2. After charge #2 processes, this charge no longer qualifies so it loses the discount

---

### Flows {#flows}

Does this impact flows? Maybe not

#### Work to do

- [QA] Ensure that flows work even if there are multiple queued charges from a single purchase item  

---

### Contract sync {#contract-sync}

What happens with syncing contracts? I think this should work fine as is. We will just sync the next upcoming charge. Once that charge processes, we'll use the one after it, and so on.

#### Work to do

- [QA] Ensure that contract sync works as expected when there are multiple queued charges for a single purchase item  

---

### Other

charge\_activity records  
upcoming charge emails  
maybe charge related events

## Open questions {#open-questions}

1. [Existing subscription updates] What happens when a customer/merchant takes an action on a purchase\_item when there are multiple queued charges?  
2. [SCI checkout] How do we accurately find the correct plan during SCI checkout?  
3. [Error charge processing] What should happen when a customer has 4 charges and the next upcoming one fails to process?  
4. [Discounts] Is it going to be a pain point if discounts with duration usage limits apply to charges initially but then fall off as other charges process?  
5. [Prepaids] How are prepaids going to work?  
6. How many places just assume there is 1 charge purchase item record for a given purchase item?  
7. What sort of FE work, if any, will be required to show multiple QUEUED charges like this in the customer/merchant portal?  
8. Is there a special customer portal/merchant portal UI for bundles?  
9. How are bundle products filtered?  
10. How do bundle\_product\_plans fit into plan selection?  
11. Are we picking the right plans for dynamic bundles?  
12. Can we start using the plan to create the dynamic bundle subscription?
