/**
 * The service catalogue and the rich content for each service page.
 *
 * The catalogue (code, name, category, duration, price) matches the services table in the
 * database. When the API is reachable its values win, so a price changed in the console shows on
 * the site; this file keeps the site complete when it is not (and gives the pages their copy).
 */

export type ServiceGroup = 'preventive' | 'restorative' | 'cosmetic' | 'surgical-orthodontic'

export interface ServiceContent {
  code: string
  slug: string
  name: string
  group: ServiceGroup
  minutes: number
  price: number
  /** Typical total cost range shown on the detail page. */
  range: [number, number]
  summary: string
  overview: string
  helps: string[]
  steps: string[]
  aftercare: string[]
  faqs: { q: string; a: string }[]
  related: string[]
}

export const groups: Record<ServiceGroup, { title: string; text: string; image: string }> = {
  preventive: {
    title: 'Preventive care',
    text: 'Checkups, cleanings and early care that keep problems small.',
    image: 'service-preventive',
  },
  restorative: {
    title: 'Restorative care',
    text: 'Fillings, crowns and root canals that repair and protect teeth.',
    image: 'service-restorative',
  },
  cosmetic: {
    title: 'Cosmetic care',
    text: 'Whitening and smile care for a brighter, natural look.',
    image: 'service-cosmetic',
  },
  'surgical-orthodontic': {
    title: 'Surgical and orthodontic care',
    text: 'Extractions, implants, aligners and urgent visits.',
    image: 'service-surgical',
  },
}

export const slugify = (name: string): string =>
  name
    .toLowerCase()
    .replace(/\(.*?\)/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')

function service(
  code: string,
  name: string,
  group: ServiceGroup,
  minutes: number,
  price: number,
  range: [number, number],
  summary: string,
  overview: string,
  helps: string[],
  steps: string[],
  aftercare: string[],
  faqs: { q: string; a: string }[],
  related: string[],
): ServiceContent {
  return {
    code,
    slug: slugify(name),
    name,
    group,
    minutes,
    price,
    range,
    summary,
    overview,
    helps,
    steps,
    aftercare,
    faqs,
    related,
  }
}

export const services: ServiceContent[] = [
  service(
    'SV01',
    'Comprehensive Exam and X-rays',
    'preventive',
    60,
    145,
    [145, 220],
    'A full examination of teeth, gums and bite with digital x-rays.',
    'Your first visit is a thorough look at your mouth: teeth, gums, bite, jaw and the soft tissues. Digital x-rays show what cannot be seen directly. You leave with a clear picture of your oral health and a plan.',
    [
      'New patients',
      'Anyone who has not had a full exam in over a year',
      'People starting orthodontic or implant planning',
    ],
    [
      'Review of your health history and concerns',
      'Digital x-rays when they are needed',
      'Examination of teeth, gums, bite and the oral cancer screen',
      'A conversation about findings and a written plan',
    ],
    [
      'You can eat and drink normally straight away',
      'Tell us if anything feels different over the next days',
    ],
    [
      {
        q: 'Do I need x-rays at every visit?',
        a: 'No. We take them when they are useful for you, usually every one to two years for healthy adults.',
      },
      {
        q: 'Is the radiation safe?',
        a: 'Digital x-rays use very low doses, and we cover you with a protective apron.',
      },
    ],
    ['SV02', 'SV03'],
  ),
  service(
    'SV02',
    'Routine Exam and Cleaning',
    'preventive',
    45,
    120,
    [120, 180],
    'A checkup and professional cleaning to keep teeth and gums healthy.',
    'A routine visit removes the plaque and tartar that brushing cannot, and lets your dentist catch small problems while they are easy to treat. Most people benefit from a visit every six months.',
    [
      'Adults and children with healthy gums',
      'Anyone who wants to keep treatment simple and small',
      'Patients on a regular recall schedule',
    ],
    [
      'A short check of your health history and any concerns',
      'Gentle cleaning above and below the gum line, then polishing',
      'Examination by your dentist',
      'Advice for brushing and flossing that suits you',
    ],
    [
      'Teeth may feel sensitive for a day',
      'Avoid very hot or cold drinks if they bother you',
      'Keep brushing twice a day and clean between teeth daily',
    ],
    [
      {
        q: 'Does a cleaning hurt?',
        a: 'It should not. Tell us if anything is uncomfortable and we will adjust or numb the area.',
      },
      {
        q: 'How often should I come?',
        a: 'Every six months for most people. Gum disease or a high cavity risk may call for more often.',
      },
    ],
    ['SV03', 'SV04', 'SV11'],
  ),
  service(
    'SV03',
    'Deep Cleaning (per quadrant)',
    'preventive',
    60,
    220,
    [220, 880],
    'Scaling and root planing below the gum line to treat early gum disease.',
    'When plaque and tartar collect below the gum line, gums become inflamed and can pull away from the teeth. A deep cleaning removes the buildup from the roots and smooths them so the gums can heal. It is done one section of the mouth at a time.',
    [
      'Patients with bleeding, swollen or receding gums',
      'Anyone told they have gum pockets deeper than normal',
      'People with a long gap since the last cleaning',
    ],
    [
      'Numbing of the area so you are comfortable',
      'Removal of tartar from above and below the gum line',
      'Smoothing of the root surfaces',
      'A follow up visit to check how the gums have healed',
    ],
    [
      'Gums may be tender and a little sore for a few days',
      'Rinse with warm salt water and eat soft foods that day',
      'Brush gently and keep cleaning between teeth',
    ],
    [
      {
        q: 'Why is it priced per quadrant?',
        a: 'The mouth is treated in four sections. Many patients need two or four, and we explain which before starting.',
      },
      {
        q: 'Will my gums go back to normal?',
        a: 'Early gum disease often improves a great deal with deep cleaning and good home care.',
      },
    ],
    ['SV02', 'SV01'],
  ),
  service(
    'SV04',
    'Tooth Colored Filling',
    'restorative',
    45,
    210,
    [210, 450],
    'A natural looking filling that repairs a cavity and restores the tooth.',
    'A tooth colored filling replaces the decayed part of a tooth with a material that matches its shade. It bonds to the tooth, so we remove less of it, and it is hard to see.',
    [
      'Patients with a cavity or a small chip',
      'Anyone replacing an older metal filling that has worn',
      'People who want repairs that blend in',
    ],
    [
      'Numbing so the visit is comfortable',
      'Removal of the decay',
      'Placement of the filling in layers, hardened with a light',
      'Shaping and polishing so your bite feels natural',
    ],
    [
      'Avoid chewing hard foods until the numbness wears off',
      'Mild sensitivity for a few days is normal',
      'Call us if your bite feels high or the sensitivity lasts',
    ],
    [
      {
        q: 'How long does a filling last?',
        a: 'Many last a decade or more, depending on size, where it is and how you care for it.',
      },
      {
        q: 'Is it covered by insurance?',
        a: 'Most plans cover a large share of fillings. We check your plan and give you an estimate first.',
      },
    ],
    ['SV05', 'SV06', 'SV02'],
  ),
  service(
    'SV05',
    'Porcelain Crown',
    'restorative',
    90,
    1150,
    [1150, 1600],
    'A custom porcelain cap that protects and restores a damaged tooth.',
    'A crown covers a tooth that is cracked, heavily filled or weakened, restoring its shape, strength and appearance. Porcelain is chosen for its natural look and lasting wear.',
    [
      'Teeth with large fillings or cracks',
      'Teeth after root canal treatment',
      'Worn or misshapen teeth',
    ],
    [
      'Shaping the tooth and taking a precise digital impression',
      'A temporary crown while your final one is made',
      'A second visit to fit and bond the porcelain crown',
      'Adjustment so it fits comfortably',
    ],
    [
      'Be careful with sticky or very hard foods while the temporary is in place',
      'Floss by sliding the floss out sideways rather than lifting it',
      'A crown can last many years with good care',
    ],
    [
      {
        q: 'How many visits does a crown need?',
        a: 'Two. The first prepares the tooth and the second fits the finished crown.',
      },
      {
        q: 'Will it look like my other teeth?',
        a: 'Yes. We match the shade and shape to the teeth around it.',
      },
    ],
    ['SV06', 'SV04', 'SV08'],
  ),
  service(
    'SV06',
    'Root Canal Therapy',
    'restorative',
    90,
    980,
    [980, 1500],
    'Treatment that removes infected tissue inside a tooth and seals it.',
    'When the soft tissue inside a tooth is infected or inflamed, a root canal removes it, cleans the space and seals it, so you can keep your tooth and stop the pain. Modern treatment is much like having a filling.',
    [
      'Patients with a lasting toothache or sensitivity to heat',
      'Teeth with deep decay or an injury',
      'Swelling near a tooth',
    ],
    [
      'Numbing of the tooth and surrounding area',
      'Removal of the infected tissue and cleaning of the canals',
      'Sealing of the canals',
      'A crown in a later visit to protect the tooth',
    ],
    [
      'Soreness for a few days is common and responds to usual pain relief as your dentist advises',
      'Avoid chewing on the tooth until it is crowned',
      'Call us if swelling or pain gets worse',
    ],
    [
      {
        q: 'Does a root canal hurt?',
        a: 'The area is numb, so most patients feel pressure only. The treatment relieves the pain that brought you in.',
      },
      {
        q: 'Why do I need a crown afterwards?',
        a: 'A treated tooth can be brittle. A crown protects it from breaking.',
      },
    ],
    ['SV05', 'SV07', 'SV14'],
  ),
  service(
    'SV07',
    'Simple Extraction',
    'surgical-orthodontic',
    45,
    240,
    [240, 400],
    'Removal of a tooth that is visible above the gum line.',
    'Sometimes a tooth cannot be saved because of decay, damage or crowding. A simple extraction removes it gently under local anesthetic, and we talk through ways to replace it.',
    [
      'Teeth too damaged to repair',
      'Teeth removed to make room for orthodontic care',
      'Loose teeth from advanced gum disease',
    ],
    [
      'Numbing and a check that you are comfortable',
      'Gentle loosening and removal of the tooth',
      'Gauze and instructions to help a clot form',
      'A discussion of replacement options',
    ],
    [
      'Bite on gauze for the time we advise and rest that day',
      'Avoid straws, smoking and spitting for 24 hours',
      'Eat soft, cool foods and keep rinsing gently after the first day',
    ],
    [
      {
        q: 'What if I am nervous?',
        a: 'Tell us. We can offer sedation and we stop whenever you ask.',
      },
      {
        q: 'Should I replace the tooth?',
        a: 'Often yes, to protect your bite. We will explain implants, bridges and other choices.',
      },
    ],
    ['SV08', 'SV09', 'SV10'],
  ),
  service(
    'SV08',
    'Surgical Extraction',
    'surgical-orthodontic',
    60,
    480,
    [480, 900],
    'Removal of an impacted or broken tooth that needs a surgical approach.',
    'Teeth that are broken at the gum line, impacted, or have curved roots need a careful surgical approach. Our oral surgeon plans each case with imaging and offers sedation for comfort.',
    [
      'Wisdom teeth that are impacted or painful',
      'Teeth broken below the gum line',
      'Teeth with unusual roots',
    ],
    [
      'Imaging and a planning conversation',
      'Numbing, with sedation if you choose it',
      'Careful removal, with stitches where needed',
      'Detailed written aftercare and a check by phone',
    ],
    [
      'Rest for the day and keep your head raised',
      'Use ice in short periods for the first day',
      'Follow the medicine advice you are given and keep the mouth clean',
    ],
    [
      {
        q: 'Can I be asleep?',
        a: 'We offer oral and nitrous sedation. Your surgeon will recommend what suits you.',
      },
      {
        q: 'When can I return to work?',
        a: 'Many people return after a day or two. Your surgeon will advise you.',
      },
    ],
    ['SV07', 'SV09', 'SV10'],
  ),
  service(
    'SV09',
    'Dental Implant Consultation',
    'surgical-orthodontic',
    45,
    90,
    [90, 90],
    'An assessment and planning visit for replacing missing teeth with implants.',
    'An implant replaces a missing tooth root with a small titanium post and a crown on top. The consultation checks whether implants suit you, and explains the steps, timing and cost.',
    [
      'People with one or more missing teeth',
      'Patients with loose dentures',
      'Those facing an extraction',
    ],
    [
      'Review of your health and goals',
      '3D imaging of the area',
      'Discussion of options, timing and cost',
      'A written treatment plan',
    ],
    ['There is no recovery after a consultation', 'Bring questions and any earlier x-rays'],
    [
      {
        q: 'Am I too old for implants?',
        a: 'Age alone is not a barrier. Healthy gums and enough bone matter most.',
      },
      {
        q: 'How long does the whole process take?',
        a: 'Often three to six months from placement to the final crown, depending on healing.',
      },
    ],
    ['SV10', 'SV07'],
  ),
  service(
    'SV10',
    'Dental Implant Placement',
    'surgical-orthodontic',
    120,
    3200,
    [3200, 4500],
    'Surgical placement of a dental implant to replace a missing tooth.',
    'Our oral surgeon places the implant under local anesthetic, with sedation if you wish. Over the following months the implant joins with the bone, and a custom crown completes the tooth.',
    [
      'Patients with healthy gums and enough bone',
      'Anyone replacing a single tooth or several',
      'People who want a fixed alternative to dentures',
    ],
    [
      'Numbing and optional sedation',
      'Placement of the implant post',
      'A healing period of a few months',
      'Fitting of the abutment and crown',
    ],
    [
      'Soreness and mild swelling for a few days are expected',
      'Eat soft foods at first and keep the area clean as shown',
      'Attend each follow up so we can check healing',
    ],
    [
      {
        q: 'Is placement painful?',
        a: 'The area is numb during the procedure. Most patients describe soreness afterwards, not sharp pain.',
      },
      { q: 'How long do implants last?', a: 'With good care they can last for decades.' },
    ],
    ['SV09', 'SV05'],
  ),
  service(
    'SV11',
    'Professional Teeth Whitening',
    'cosmetic',
    60,
    420,
    [420, 600],
    'In office whitening that brightens teeth in a single visit.',
    'Professional whitening lifts stains from coffee, tea and age using a medical grade gel under protective coverings. It is faster and more even than over the counter kits, and we manage sensitivity.',
    [
      'Healthy teeth with surface stains',
      'Patients preparing for an event',
      'Anyone who wants a few shades brighter',
    ],
    [
      'A check that your teeth and gums are healthy',
      'Protection for your gums and lips',
      'Application of the whitening gel in short rounds',
      'Shade comparison before you leave',
    ],
    [
      'Avoid dark drinks and foods for two days',
      'Sensitivity for a day is common',
      'Brush with a gentle toothpaste',
    ],
    [
      {
        q: 'How long do results last?',
        a: 'Often a year or more. Coffee, tea and smoking shorten it.',
      },
      {
        q: 'Is it safe for my enamel?',
        a: 'When done by a dentist on healthy teeth, yes. We check first.',
      },
    ],
    ['SV02', 'SV05'],
  ),
  service(
    'SV12',
    'Orthodontic Consultation',
    'surgical-orthodontic',
    45,
    75,
    [75, 75],
    'An assessment of alignment and bite with a discussion of treatment options.',
    'Whether you are thinking about clear aligners for yourself or a growing child, the consultation looks at alignment and bite, and explains choices, timing and cost.',
    [
      'Children and teens with crowding or a bite concern',
      'Adults who want straighter teeth',
      'Patients unhappy with a past result',
    ],
    [
      'Photos and a scan or impressions',
      'Examination of teeth, jaws and bite',
      'A discussion of options and expected time',
      'A written estimate',
    ],
    ['No recovery is needed', 'You are under no obligation to begin treatment'],
    [
      {
        q: 'At what age should a child be seen?',
        a: 'Around age seven is a good time for a first check, earlier if you have concerns.',
      },
      {
        q: 'Are aligners right for everyone?',
        a: 'Not always. We tell you honestly what will work best.',
      },
    ],
    ['SV13', 'SV01'],
  ),
  service(
    'SV13',
    'Clear Aligner Treatment (plan fee)',
    'surgical-orthodontic',
    30,
    4800,
    [3800, 5500],
    'A planned course of clear aligners to straighten teeth.',
    'Clear aligners are a series of custom trays that move teeth step by step. They are removable, comfortable and hard to see. The plan fee covers planning, all trays and your check ups.',
    [
      'Teens and adults with mild to moderate crowding or gaps',
      'Patients who prefer a discreet option',
      'People who can wear trays for most of the day',
    ],
    [
      'A digital scan and a 3D preview of the plan',
      'Delivery of your first set of trays',
      'Check ups every six to eight weeks',
      'A retainer to keep the result',
    ],
    [
      'Wear trays for the hours advised and take them out to eat',
      'Clean trays and teeth before putting them back',
      'Wear your retainer as directed once treatment ends',
    ],
    [
      {
        q: 'How long does it take?',
        a: 'Most plans take six to eighteen months, depending on the changes needed.',
      },
      {
        q: 'Does it hurt?',
        a: 'Teeth feel tight for a day or two with each new tray, which is normal.',
      },
    ],
    ['SV12', 'SV02'],
  ),
  service(
    'SV14',
    'Emergency Visit',
    'surgical-orthodontic',
    30,
    160,
    [160, 400],
    'A prompt visit for severe pain, a broken tooth or another urgent problem.',
    'We keep time free every day for urgent problems: a toothache that will not settle, a broken or knocked out tooth, swelling, or a lost filling or crown. We relieve the problem first and plan the rest with you.',
    [
      'Severe or lasting toothache',
      'Broken, chipped or knocked out teeth',
      'A lost filling or crown',
    ],
    [
      'A quick call so we can prepare',
      'A focused examination and an x-ray if needed',
      'Treatment to relieve pain or protect the tooth',
      'A plan for any further care',
    ],
    [
      'Follow the advice we give you for pain and care',
      'Keep a knocked out tooth moist in milk and bring it with you',
      'Call 911 for trouble breathing, spreading swelling or bleeding that will not stop',
    ],
    [
      {
        q: 'Can I be seen today?',
        a: 'Usually yes. Call our emergency line and we will find the earliest time.',
      },
      {
        q: 'What should I do with a knocked out tooth?',
        a: 'Hold it by the crown, rinse gently, keep it in milk and come straight in.',
      },
    ],
    ['SV06', 'SV07'],
  ),
]

export const serviceBySlug = (slug: string): ServiceContent | undefined =>
  services.find((s) => s.slug === slug)
export const serviceByCode = (code: string): ServiceContent | undefined =>
  services.find((s) => s.code === code)
export const homeServices = ['SV02', 'SV01', 'SV04', 'SV05', 'SV06', 'SV11', 'SV13', 'SV14']
  .map((code) => serviceByCode(code))
  .filter((s): s is ServiceContent => Boolean(s))
