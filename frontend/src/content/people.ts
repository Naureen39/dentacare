/** The team. Names and credentials are fictional and match the demonstration database. */

export interface DentistProfile {
  slug: string
  name: string
  short: string
  specialty: string
  credentials: string
  image: string
  bio: string
  education: string[]
  languages: string[]
  focus: string[]
}

export const dentists: DentistProfile[] = [
  {
    slug: 'priya-raman',
    name: 'Dr. Priya Raman',
    short: 'Dr. Raman',
    specialty: 'General dentistry',
    credentials: 'DDS',
    image: 'dentist-1',
    bio: 'Dr. Raman leads our general care team. She is known for explaining each step before she begins and for long, careful appointments that never feel rushed.',
    education: [
      'DDS, fictional University School of Dentistry',
      'Continuing study in restorative and preventive dentistry',
    ],
    languages: ['English', 'Tamil', 'Hindi'],
    focus: ['Checkups and cleanings', 'Fillings and crowns', 'Anxious patients'],
  },
  {
    slug: 'marcus-lindqvist',
    name: 'Dr. Marcus Lindqvist',
    short: 'Dr. Lindqvist',
    specialty: 'Orthodontics',
    credentials: 'DDS, MS',
    image: 'dentist-2',
    bio: 'Dr. Lindqvist straightens teeth for teens and adults. He plans every case on screen so you can see the expected result before you begin.',
    education: [
      'DDS, fictional University School of Dentistry',
      'MS in Orthodontics, fictional Institute of Dental Sciences',
    ],
    languages: ['English', 'Swedish'],
    focus: ['Clear aligners', 'Early orthodontic checks', 'Bite correction'],
  },
  {
    slug: 'hannah-okafor',
    name: 'Dr. Hannah Okafor',
    short: 'Dr. Okafor',
    specialty: 'Pediatric dentistry',
    credentials: 'DDS, MS',
    image: 'dentist-3',
    bio: 'Dr. Okafor makes the dentist a place children look forward to. She sees children from their first tooth and helps parents with habits that prevent cavities.',
    education: [
      'DDS, fictional University School of Dentistry',
      'Certificate in Pediatric Dentistry, fictional Children’s Hospital',
    ],
    languages: ['English', 'Igbo', 'French'],
    focus: ['First visits', 'Cavity prevention', 'Children with anxiety or special needs'],
  },
  {
    slug: 'daniel-reyes',
    name: 'Dr. Daniel Reyes',
    short: 'Dr. Reyes',
    specialty: 'Endodontics',
    credentials: 'DDS, MS',
    image: 'dentist-4',
    bio: 'Dr. Reyes treats the inside of the tooth. He uses magnification to make root canal treatment precise, quick and comfortable.',
    education: [
      'DDS, fictional University School of Dentistry',
      'MS in Endodontics, fictional Institute of Dental Sciences',
    ],
    languages: ['English', 'Spanish'],
    focus: ['Root canal therapy', 'Retreatment', 'Dental injuries'],
  },
  {
    slug: 'sofia-marchetti',
    name: 'Dr. Sofia Marchetti',
    short: 'Dr. Marchetti',
    specialty: 'Periodontics',
    credentials: 'DDS, MS',
    image: 'dentist-5',
    bio: 'Dr. Marchetti cares for the gums and the bone that hold teeth in place. She helps patients keep their natural teeth for life.',
    education: [
      'DDS, fictional University School of Dentistry',
      'MS in Periodontology, fictional Institute of Dental Sciences',
    ],
    languages: ['English', 'Italian'],
    focus: ['Gum disease', 'Deep cleaning', 'Gum health around implants'],
  },
  {
    slug: 'theodore-whitfield',
    name: 'Dr. Theodore Whitfield',
    short: 'Dr. Whitfield',
    specialty: 'Oral surgery',
    credentials: 'DDS, MD',
    image: 'dentist-6',
    bio: 'Dr. Whitfield performs extractions and places implants. He plans carefully with 3D imaging and offers sedation so surgery is calm.',
    education: [
      'DDS, fictional University School of Dentistry',
      'Residency in Oral and Maxillofacial Surgery, fictional Medical Center',
    ],
    languages: ['English'],
    focus: ['Wisdom teeth', 'Dental implants', 'Surgical extractions'],
  },
  {
    slug: 'amara-nwosu',
    name: 'Dr. Amara Nwosu',
    short: 'Dr. Nwosu',
    specialty: 'Cosmetic dentistry',
    credentials: 'DDS',
    image: 'dentist-7',
    bio: 'Dr. Nwosu joined the practice to bring natural looking smile care to patients who want to feel confident, with an honest view of what is worth doing.',
    education: [
      'DDS, fictional University School of Dentistry',
      'Advanced training in aesthetic dentistry',
    ],
    languages: ['English', 'Igbo'],
    focus: ['Teeth whitening', 'Natural looking fillings and crowns', 'Smile planning'],
  },
]

export const dentistBySlug = (slug: string): DentistProfile | undefined =>
  dentists.find((d) => d.slug === slug)
export const dentistByName = (name: string): DentistProfile | undefined =>
  dentists.find((d) => d.name === name)

export interface Article {
  slug: string
  title: string
  summary: string
  image: string
  minutes: number
  published: string
  body: { heading?: string; text: string }[]
  source?: string
}

export const articles: Article[] = [
  {
    slug: 'brushing-and-flossing-well',
    title: 'Brushing and flossing: how to do it well',
    image: 'article-1',
    minutes: 4,
    published: '2026-03-02',
    summary: 'Two minutes twice a day, and a few minutes with floss, prevent most dental problems.',
    body: [
      {
        text: 'Most cavities and gum disease begin with plaque, a sticky film of bacteria. Removing it every day is the single most useful thing you can do for your teeth.',
      },
      {
        heading: 'Brushing',
        text: 'Brush for two minutes, twice a day, with a soft brush and fluoride toothpaste. Angle the bristles toward the gum line and use short, gentle strokes. Brushing hard does not clean better and can wear gums. Replace your brush every three months.',
      },
      {
        heading: 'Cleaning between teeth',
        text: 'A brush cannot reach the sides of your teeth. Clean between them once a day with floss or small interdental brushes. Curve the floss around each tooth and slide it just under the gum edge.',
      },
      {
        heading: 'Rinse less, spit more',
        text: 'After brushing, spit out the toothpaste but do not rinse with water. The fluoride that stays on your teeth keeps protecting them.',
      },
    ],
    source:
      'Adapted from public guidance of the U.S. National Institute of Dental and Craniofacial Research.',
  },
  {
    slug: 'your-childs-first-dental-visit',
    title: 'Your child’s first dental visit',
    image: 'article-2',
    minutes: 3,
    published: '2026-03-18',
    summary: 'When to go, what happens, and how to make it a good experience.',
    body: [
      {
        text: 'Children should see a dentist by their first birthday or when the first tooth appears. Early visits are short and mostly about getting comfortable.',
      },
      {
        heading: 'What happens',
        text: 'The dentist looks at the teeth and gums, may gently clean them, and shows you how to care for your child’s mouth. There is rarely any treatment at a first visit.',
      },
      {
        heading: 'How to help',
        text: 'Speak about the visit in a calm, positive way. Avoid words like hurt or shot. Book a time when your child is rested, and bring a favourite toy if it helps.',
      },
    ],
    source:
      'Adapted from public guidance of the U.S. National Institute of Dental and Craniofacial Research.',
  },
  {
    slug: 'what-to-do-in-a-dental-emergency',
    title: 'What to do in a dental emergency',
    image: 'article-3',
    minutes: 3,
    published: '2026-04-06',
    summary: 'Simple steps for a knocked out tooth, a broken tooth and a bad toothache.',
    body: [
      {
        text: 'Call 911 for trouble breathing, swelling that is spreading to the face or neck, or bleeding that will not stop. For other urgent problems call our emergency line at once.',
      },
      {
        heading: 'A knocked out tooth',
        text: 'Pick it up by the crown, not the root. Rinse it gently if dirty, and try to place it back in its socket. If you cannot, keep it in milk and see a dentist within the hour.',
      },
      {
        heading: 'A broken tooth',
        text: 'Rinse your mouth with warm water and save any pieces. Use a cold compress on the face to reduce swelling.',
      },
      {
        heading: 'A toothache',
        text: 'Rinse with warm water and gently clean between teeth to remove trapped food. Do not put medicine on the gum. Call us so we can see you soon.',
      },
    ],
    source:
      'Adapted from public guidance of the U.S. National Institute of Dental and Craniofacial Research and MedlinePlus.',
  },
  {
    slug: 'understanding-gum-disease',
    title: 'Understanding gum disease',
    image: 'article-4',
    minutes: 4,
    published: '2026-04-22',
    summary: 'Bleeding gums are a warning. Early gum disease can be reversed.',
    body: [
      {
        text: 'Gum disease starts as gingivitis: red, swollen gums that bleed when you brush. At this stage it can be reversed with a cleaning and good daily care.',
      },
      {
        heading: 'When it advances',
        text: 'Left alone, gingivitis can become periodontitis, where the gums pull away and the bone around the teeth is damaged. It is a leading cause of tooth loss in adults.',
      },
      {
        heading: 'Who is at risk',
        text: 'Smoking, diabetes, some medicines and a family history all raise the risk. Regular visits let us measure your gums and act early.',
      },
      {
        heading: 'What helps',
        text: 'Brush twice a day, clean between teeth daily, avoid tobacco and keep your regular visits. If you notice bleeding, bad breath that does not go away, or loose teeth, book an appointment.',
      },
    ],
    source:
      'Adapted from public guidance of the U.S. National Institute of Dental and Craniofacial Research.',
  },
]

export const articleBySlug = (slug: string): Article | undefined =>
  articles.find((a) => a.slug === slug)
